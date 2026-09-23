import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time

from .config import Settings
from .content import POST_URN, post_identity, post_url, snapshot_post
from .db import Database, encoded
from .network import validate_url
from .sync import Sync, safe_error

log = logging.getLogger(__name__)
HEALTH = Path('/tmp/linkedin-archive-health.json')


def heartbeat(ok):
    tmp = HEALTH.with_suffix('.tmp')
    tmp.write_text(json.dumps({'at': time.time(), 'ok': ok}))
    tmp.replace(HEALTH)


def main():
    parser = argparse.ArgumentParser(description='Archive your own LinkedIn posts in MariaDB')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('run', help='Run scheduled synchronization')
    once = sub.add_parser('sync', help='Run a single cycle')
    once.add_argument('--force-snapshot', action='store_true')
    sub.add_parser('init-db')
    sub.add_parser('status')
    sub.add_parser('healthcheck')
    sub.add_parser('api', help='Serve published posts, media and authenticated raw data')
    imported = sub.add_parser('import-json', help='Import a saved MEMBER_SHARE_INFO API response')
    imported.add_argument('path', type=Path)
    fetched = sub.add_parser('fetch', help='Archive/enrich a specific own post without API access')
    fetched.add_argument('url')
    sub.add_parser('enrich', help='Process pending media/links without an API request')
    exported = sub.add_parser('export', help='Create a JSON export for a future website')
    exported.add_argument('--published-only', action='store_true')
    published = sub.add_parser('publish', help='Mark a post for inclusion in website exports; does not publish online')
    published.add_argument('post_key')
    published.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level, format='%(asctime)s %(levelname)s %(message)s')
    if args.command == 'healthcheck':
        try:
            state = json.loads(HEALTH.read_text())
            return 0 if state['ok'] and time.time() - state['at'] < max(900, settings.interval * 3) else 1
        except (OSError, ValueError, KeyError):
            return 1
    if args.command == 'api':
        from .api import serve
        return serve(settings)
    if args.command in {'run', 'sync'} and (not settings.token or settings.token.startswith('REPLACE_')):
        log.error('Set LINKEDIN_ACCESS_TOKEN in .env, then recreate the archive container')
        return 2
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    if args.command == 'run':
        while not stop.is_set():
            ok = False
            db = worker = None
            try:
                heartbeat(True)
                db = Database(settings)
                db.init()
                worker = Sync(settings, db)
                ok = worker.run(stop=stop)
            except Exception as exc:
                log.error('Sync cycle failed: %s', safe_error(exc))
            finally:
                if worker:
                    worker.close()
                if db:
                    db.close()
            heartbeat(ok)
            stop.wait(settings.interval)
        return 0
    db = worker = None
    try:
        db = Database(settings)
        db.init()
        if args.command == 'init-db':
            return 0
        if args.command == 'status':
            print(encoded({'posts': db.rows('SELECT enrichment_status,COUNT(*) AS count FROM posts GROUP BY enrichment_status'),
                           'media': db.rows('SELECT download_status,COUNT(*) AS count FROM post_media WHERE active=TRUE GROUP BY download_status'),
                           'state': db.rows('SELECT * FROM sync_state')}))
            return 0
        if args.command == 'export':
            settings.export_dir.mkdir(parents=True, exist_ok=True)
            target = settings.export_dir / ('website.json' if args.published_only else 'archive.json')
            data = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
                    'posts': db.export(args.published_only)}
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + '\n')
            temp.replace(target)
            print(str(target))
            return 0
        if args.command == 'publish':
            with db.transaction():
                changed = db.execute('UPDATE posts SET publish_enabled=%s WHERE post_key=%s AND deleted_at IS NULL',
                                     (not args.disable, args.post_key))
            if not changed and not db.rows('SELECT id FROM posts WHERE post_key=%s AND deleted_at IS NULL',
                                           (args.post_key,)):
                log.error('No archived post with key %s; nothing was changed', args.post_key)
                return 1
            print(('Disabled' if args.disable else 'Enabled') + f' website publication for {args.post_key}')
            return 0
        if args.command == 'import-json':
            payload = json.loads(args.path.read_text(encoding='utf-8-sig'))
            elements = payload.get('elements', [])
            if isinstance(elements, dict):
                elements = [elements]
            count = 0
            if not db.lock():
                raise RuntimeError('Another sync is active')
            try:
                with db.transaction():
                    for element in elements:
                        for row in element.get('snapshotData', []):
                            post = snapshot_post(row)
                            if post:
                                db.upsert_post(post)
                                count += 1
                print(f'{count} records imported')
            finally:
                db.unlock()
            return 0
        if args.command == 'fetch':
            validate_url(args.url, ('linkedin.com',))
            key = post_identity(args.url)
            if not POST_URN.fullmatch(key):
                raise ValueError('Use a feed/update URL containing the share, ugcPost or activity URN')
            if not db.lock():
                raise RuntimeError('Another sync is active')
            try:
                with db.transaction():
                    db.upsert_post({'post_key': key, 'source_url': post_url(key),
                                    'content_text': None, 'raw': {'manually_requested': True}})
                    db.execute("UPDATE posts SET next_enrichment_at='1970-01-01',enrichment_status='pending' WHERE post_key=%s", (key,))
                worker = Sync(replace(settings, max_posts=1), db)
                worker.enrich(stop)
                result = db.rows('SELECT enrichment_status FROM posts WHERE post_key=%s', (key,))[0]
                return 0 if result['enrichment_status'] == 'complete' else 1
            finally:
                db.unlock()
        worker = Sync(settings, db)
        return 0 if worker.run(getattr(args, 'force_snapshot', False), stop, args.command != 'enrich') else 1
    except Exception as exc:
        log.error('%s', safe_error(exc))
        return 1
    finally:
        if worker:
            worker.close()
        if db:
            db.close()


if __name__ == '__main__':
    sys.exit(main())
