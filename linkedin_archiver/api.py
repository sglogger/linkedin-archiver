"""Small read-only HTTP service for the public website and private exports."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import queue
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .db import Database


log = logging.getLogger(__name__)
MEDIA_PATH = re.compile(r'[0-9a-f]{2}/[0-9a-f]{64}\.(?:jpg|png|gif|webp|avif|mp4|webm|pdf)')
POST_KEY = re.compile(r'urn:li:(?:share|ugcPost|activity):\d+')


def key_matches(supplied: str, expected: str) -> bool:
    # Header values arrive latin-1 decoded; compare_digest rejects non-ASCII str.
    return compare_digest(supplied.encode('utf-8', 'replace'), expected.encode('utf-8'))


class Pool:
    """Reuses a few MariaDB connections instead of dialing one per request.

    Every checkout rolls back first: without it the reused connection would keep
    serving its old REPEATABLE READ snapshot and never see newly published posts.
    """

    def __init__(self, settings, size=4):
        self.settings = settings
        self.idle = queue.LifoQueue(maxsize=size)

    @staticmethod
    def discard(db):
        try:
            db.close()
        except Exception:
            pass

    def reusable(self, db) -> bool:
        try:
            # No reconnect: a dropped connection is discarded and replaced below,
            # which also keeps the session settings from __init__ intact.
            db.conn.ping(reconnect=False)
            db.conn.rollback()
            return True
        except Exception:
            self.discard(db)
            return False

    @contextmanager
    def connection(self):
        db = None
        while db is None:
            try:
                candidate = self.idle.get_nowait()
            except queue.Empty:
                break
            if self.reusable(candidate):
                db = candidate
        if db is None:
            db = Database(self.settings)
        try:
            yield db
        except Exception:
            self.discard(db)
            raise
        else:
            try:
                db.conn.rollback()
                self.idle.put_nowait(db)
            except Exception:
                self.discard(db)

    def close(self):
        while True:
            try:
                self.discard(self.idle.get_nowait())
            except queue.Empty:
                return


def website_post(post, base_url):
    result = {key: post[key] for key in (
        'post_key', 'source_url', 'canonical_url', 'published_at', 'visibility',
        'content_text', 'content_html', 'content_source', 'reaction_count',
        'comment_count', 'engagement_updated_at', 'links',
        'reshare_author', 'reshare_author_url', 'reshare_html')}
    for name in ('published_at', 'engagement_updated_at'):
        if isinstance(result[name], datetime):
            result[name] = result[name].isoformat() + 'Z'
    result['media'] = [{
        'position': item['position'], 'kind': item['kind'], 'role': item['role'],
        'alt_text': item['alt_text'], 'content_type': item['content_type'],
        'size_bytes': item['size_bytes'], 'download_status': item['download_status'],
        'media_url': base_url + item['local_url'] if item['download_status'] == 'downloaded' and item['local_url'] else None,
    } for item in post['media']]
    return result


def pagination(query):
    try:
        limit = int(query.get('limit', ['20'])[0])
        offset = int(query.get('offset', ['0'])[0])
    except (ValueError, TypeError):
        raise ValueError('limit and offset must be integers') from None
    if not 1 <= limit <= 100 or not 0 <= offset <= 1000000:
        raise ValueError('limit must be 1–100 and offset 0–1000000')
    return limit, offset


def handler_for(settings, pool=None):
    pool = pool or Pool(settings)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'LinkedInArchive/1.0'
        headers_sent = False

        def log_message(self, fmt, *args):
            # URLs may contain the private post URN; never log request headers/keys.
            log.info('HTTP %s', args[1] if len(args) > 1 else '')

        def send_headers(self, status, content_type, length, cache='no-store'):
            self.headers_sent = True
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', cache)
            self.send_header('X-Content-Type-Options', 'nosniff')
            origin = self.headers.get('Origin')
            if origin and origin == settings.api_allowed_origin:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
            self.end_headers()

        def json_response(self, status, value):
            data = json.dumps(value, ensure_ascii=False, default=str).encode('utf-8')
            self.send_headers(status, 'application/json; charset=utf-8', len(data))
            if self.command != 'HEAD':
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if path == '/health':
                try:
                    with pool.connection() as db:
                        db.rows('SELECT 1 AS ok')
                    self.json_response(200, {'status': 'ok'})
                except Exception:
                    self.json_response(503, {'error': 'database unavailable'})
                return
            if path.startswith('/media/'):
                return self.media_response(path[len('/media/'):])
            if path not in ('/api/v1/posts', '/api/v1/raw/posts') and not path.startswith('/api/v1/posts/'):
                return self.json_response(404, {'error': 'not found'})
            private = path == '/api/v1/raw/posts'
            if private:
                supplied = self.headers.get('X-Archive-Key', '')
                if not settings.api_read_key or settings.api_read_key.startswith('REPLACE_'):
                    return self.json_response(503, {'error': 'raw API disabled'})
                if not key_matches(supplied, settings.api_read_key):
                    return self.json_response(401, {'error': 'invalid archive key'})
            try:
                limit, offset = pagination(parse_qs(parsed.query))
            except ValueError as exc:
                return self.json_response(400, {'error': str(exc)})
            try:
                with pool.connection() as db:
                    published_only = not private
                    if path.startswith('/api/v1/posts/'):
                        key = path[len('/api/v1/posts/'):]
                        if not POST_KEY.fullmatch(key):
                            return self.json_response(404, {'error': 'not found'})
                        posts = db.export(True, post_key=key)
                        if not posts:
                            return self.json_response(404, {'error': 'not found'})
                        return self.json_response(200, website_post(posts[0], settings.api_public_base_url))
                    posts = db.export(published_only, limit, offset, include_raw=private)
                    total = db.count_posts(published_only)
                if not private:
                    posts = [website_post(p, settings.api_public_base_url) for p in posts]
                self.json_response(200, {
                    'schema_version': 1,
                    'generated_at': datetime.now(timezone.utc).isoformat(),
                    'total': total,
                    'limit': limit, 'offset': offset, 'posts': posts,
                })
            except Exception:
                log.exception('API query failed')
                if not self.headers_sent:
                    self.json_response(503, {'error': 'archive unavailable'})
                else:
                    self.close_connection = True

        def media_response(self, relative):
            if not MEDIA_PATH.fullmatch(relative):
                return self.json_response(404, {'error': 'not found'})
            # Look the file up and hand the connection back before streaming, so a
            # slow client cannot hold a pooled connection for the whole download.
            try:
                with pool.connection() as db:
                    matches = db.media_for_publication(relative)
            except Exception:
                log.exception('Media lookup failed')
                return self.json_response(503, {'error': 'media unavailable'})
            if not matches:
                return self.json_response(404, {'error': 'not found'})
            root = settings.media_dir.resolve()
            target = (root / relative).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                return self.json_response(404, {'error': 'not found'})
            try:
                size = target.stat().st_size
                with target.open('rb') as media:
                    self.send_headers(200, matches[0]['content_type'] or 'application/octet-stream', size,
                                      'public, max-age=86400, immutable')
                    if self.command != 'HEAD':
                        while chunk := media.read(65536):
                            self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:
                log.exception('Media delivery failed')
                # Once the 200 header is out, a second response would corrupt the stream.
                if not self.headers_sent:
                    self.json_response(503, {'error': 'media unavailable'})
                else:
                    self.close_connection = True

    return Handler


def serve(settings):
    pool = Pool(settings)
    try:
        with ThreadingHTTPServer(('0.0.0.0', 8080), handler_for(settings, pool)) as server:
            server.daemon_threads = True
            log.info('Read-only API listening on port 8080')
            try:
                server.serve_forever(poll_interval=0.5)
            except KeyboardInterrupt:
                pass
    finally:
        pool.close()
    return 0
