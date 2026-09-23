from http.server import ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from linkedin_archiver.api import Pool, handler_for, key_matches
from linkedin_archiver.config import Settings
from linkedin_archiver.db import Database
from test_content import KEY, URL
from test_database import db


def test_api_publication_raw_key_and_media(db, tmp_path):
    media_name = 'ab/' + 'a' * 64 + '.jpg'
    file = tmp_path / media_name
    file.parent.mkdir()
    file.write_bytes(b'example image')
    with db.transaction():
        db.upsert_post({'post_key': KEY, 'source_url': URL, 'content_text': 'Hallo',
                        'content_html': '<p>Hallo</p>', 'raw': {'owner': 'private'}})
        post_id = db.rows('SELECT id FROM posts WHERE post_key=%s', (KEY,))[0]['id']
        db.execute('INSERT INTO post_media (post_id,media_key,position,kind,source_url,local_path,content_type,download_status) '
                   'VALUES (%s,%s,0,%s,%s,%s,%s,%s)',
                   (post_id, 'a' * 64, 'image', 'https://media.licdn.com/example',
                    media_name, 'image/jpeg', 'downloaded'))
    settings = Settings(token='', db_host=db.conn.host, db_port=db.conn.port,
        db_password=db.conn.password, media_dir=tmp_path, api_read_key='test-private-key')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(settings))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)

    def get(path, key=None):
        req = Request(base + path, headers={'X-Archive-Key': key} if key else {})
        with urlopen(req, timeout=3) as response:
            return response.status, response.read(), response.headers

    try:
        assert json.loads(get('/api/v1/posts')[1])['total'] == 0
        try:
            get('/media/' + media_name)
            assert False, 'unpublished media was exposed'
        except HTTPError as exc:
            assert exc.code == 404
        with db.transaction():
            db.execute('UPDATE posts SET publish_enabled=TRUE,reaction_count=81,comment_count=7 WHERE id=%s', (post_id,))
        status, data, _ = get('/api/v1/posts?limit=1&offset=0')
        item = json.loads(data)['posts'][0]
        assert status == 200 and item['reaction_count'] == 81 and item['comment_count'] == 7
        assert 'raw_snapshot' not in item and 'source_url' not in item['media'][0]
        assert get('/media/' + media_name)[1] == b'example image'
        try:
            get('/api/v1/raw/posts')
            assert False, 'raw archive was exposed'
        except HTTPError as exc:
            assert exc.code == 401
        raw = json.loads(get('/api/v1/raw/posts', 'test-private-key')[1])
        assert raw['posts'][0]['raw_snapshot']['owner'] == 'private'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_archive_key_rejects_non_ascii_header_without_crashing():
    # Header values arrive latin-1 decoded; hmac.compare_digest raises on non-ASCII str.
    assert key_matches('test-private-key', 'test-private-key')
    assert not key_matches('wrong', 'test-private-key')
    assert not key_matches('kéy', 'test-private-key')


def test_pool_reuses_rolls_back_and_drops_broken_connections(monkeypatch):
    rollbacks = []

    class FakeConnection:
        def __init__(self):
            self.closed = False

        def ping(self, reconnect=False):
            if self.closed:
                raise RuntimeError('connection gone')

        def rollback(self):
            rollbacks.append(self)

        def close(self):
            self.closed = True

    class FakeDatabase:
        def __init__(self, settings):
            self.conn = FakeConnection()

        def close(self):
            self.conn.close()

    monkeypatch.setattr('linkedin_archiver.api.Database', FakeDatabase)
    pool = Pool(object(), size=2)
    with pool.connection() as first:
        pass
    with pool.connection() as second:
        pass
    # A reused connection must be rolled back, or it keeps serving a stale snapshot.
    assert second is first and rollbacks

    try:
        with pool.connection():
            raise ValueError('query failed')
    except ValueError:
        pass
    assert first.conn.closed
    with pool.connection() as third:
        assert third is not first
    third.conn.closed = True
    with pool.connection() as fourth:
        assert fourth is not third
    pool.close()
