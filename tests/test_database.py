from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
import os
import time

import pytest

from linkedin_archiver.config import Settings
from linkedin_archiver.content import snapshot_post
from linkedin_archiver.db import Database
from linkedin_archiver.network import FetchError
from linkedin_archiver.page import parse_page
from linkedin_archiver.sync import Sync
from test_content import KEY, URL, FIXTURE, event


@pytest.fixture
def db():
    if not os.getenv('TEST_DB_HOST'):
        pytest.skip('Set TEST_DB_HOST and TEST_DB_PORT for isolated MariaDB integration tests')
    settings = Settings(token='test', db_host=os.environ['TEST_DB_HOST'],
        db_port=int(os.getenv('TEST_DB_PORT', '3306')), db_password=os.environ['TEST_DB_PASSWORD'])
    database = Database(settings)
    database.init()
    with database.transaction():
        for table in ['post_links', 'post_media', 'post_events', 'posts', 'sync_state']:
            database.execute(f'DELETE FROM {table}')
    yield database
    database.close()


def sample():
    return snapshot_post({'ShareLink': URL, 'ShareCommentary': 'Original 😀', 'Visibility': 'MEMBER_NETWORK', 'Date': '2022-09-23 06:40:24'})


def test_idempotent_import_utf8_links_and_media(db):
    with db.transaction():
        db.upsert_post(sample())
        db.upsert_post(sample())
    rows = db.rows('SELECT * FROM posts')
    assert len(rows) == 1 and rows[0]['content_text'] == 'Original 😀'
    page = parse_page(FIXTURE.read_text(), URL, KEY)
    with db.transaction():
        db.save_page(rows[0]['id'], page)
        db.save_page(rows[0]['id'], page)
        db.upsert_post(sample())
    exported = db.export()[0]
    assert len(exported['links']) == 7 and len(exported['media']) == 1
    assert 'Florian Kässberger' in exported['content_html']
    assert exported['content_source'] == 'page'
    assert exported['reaction_count'] == 81 and exported['comment_count'] == 7


def test_deleted_posts_not_resurrected_by_stale_snapshot(db):
    with db.transaction():
        db.upsert_post(sample())
        deleted = sample() | {'deleted': True}
        db.upsert_post(deleted, 'changelog')
        db.upsert_post(sample())
    assert db.export() == []
    assert db.queue(10) == []


def test_cursor_and_events_are_atomic_across_failed_pages(db):
    settings = Settings(token='test')
    start = int(time.time() * 1000) - 10000
    with db.transaction():
        db.set_state('changelog_cursor', start)
    api = Mock()
    def broken(_):
        yield [event(processedAt=start + 1000, id=1)]
        raise FetchError('second page failed')
    api.changes = broken
    worker = Sync(settings, db, api=api, reader=Mock(), downloader=Mock())
    with pytest.raises(FetchError):
        worker.changes()
    assert int(db.state('changelog_cursor')) == start
    assert db.rows('SELECT * FROM post_events') == []
    api.changes = Mock(return_value=iter([[event(processedAt=start + 1000, id=1)]]))
    worker.changes()
    assert int(db.state('changelog_cursor')) == start + 1000
    api.changes = Mock(return_value=iter([[event(processedAt=start + 1000, id=1)]]))
    worker.changes()
    assert len(db.rows('SELECT * FROM post_events')) == 1
    assert api.changes.call_args.args[0] == start + 1000


def test_media_retry_preserves_already_saved_text_and_links(db, tmp_path):
    with db.transaction():
        db.upsert_post(sample())
    settings = Settings(token='test', media_dir=tmp_path)
    reader, downloader = Mock(), Mock()
    reader.read.return_value = parse_page(FIXTURE.read_text(), URL, KEY)
    downloader.download.side_effect = FetchError('HTTP 503')
    Sync(settings, db, api=Mock(), reader=reader, downloader=downloader).enrich()
    row = db.rows('SELECT * FROM posts')[0]
    assert row['enrichment_status'] == 'partial'
    assert len(db.export()[0]['links']) == 7
    assert db.media(row['id'])[0]['download_status'] == 'failed'


def test_publication_is_opt_in_and_lock_prevents_concurrent_sync(db):
    with db.transaction():
        db.upsert_post(sample())
    assert db.export(published_only=True) == []
    with db.transaction():
        db.execute('UPDATE posts SET publish_enabled=TRUE WHERE post_key=%s', (KEY,))
    assert len(db.export(published_only=True)) == 1
    assert db.lock()
    settings = Settings(token='test', db_host=os.environ['TEST_DB_HOST'],
        db_port=int(os.getenv('TEST_DB_PORT', '3306')), db_password=os.environ['TEST_DB_PASSWORD'])
    other = Database(settings)
    try:
        assert not other.lock()
    finally:
        other.close()
        db.unlock()


def test_auto_publish_applies_to_new_posts_only(db):
    with db.transaction():
        db.upsert_post(sample())
    assert db.rows('SELECT publish_enabled FROM posts WHERE post_key=%s', (KEY,))[0]['publish_enabled'] == 0

    db.auto_publish = True
    with db.transaction():
        db.upsert_post(replace_share(KEY, 'urn:li:share:111'))
    assert db.rows('SELECT publish_enabled FROM posts WHERE post_key=%s', ('urn:li:share:111',))[0]['publish_enabled'] == 1

    # An update to the already archived post must not flip it on retroactively.
    with db.transaction():
        db.upsert_post(sample())
    assert db.rows('SELECT publish_enabled FROM posts WHERE post_key=%s', (KEY,))[0]['publish_enabled'] == 0


def test_auto_publish_never_revives_a_withdrawn_or_deleted_post(db):
    db.auto_publish = True
    with db.transaction():
        db.upsert_post(sample())
        db.execute('UPDATE posts SET publish_enabled=FALSE WHERE post_key=%s', (KEY,))
    # A later snapshot/changelog touch of the same post keeps the withdrawal.
    with db.transaction():
        db.upsert_post(sample())
    assert db.rows('SELECT publish_enabled FROM posts WHERE post_key=%s', (KEY,))[0]['publish_enabled'] == 0

    with db.transaction():
        db.upsert_post({**sample(), 'post_key': 'urn:li:share:222',
                        'source_url': 'https://www.linkedin.com/feed/update/urn:li:share:222',
                        'deleted': True})
    row = db.rows('SELECT publish_enabled,deleted_at FROM posts WHERE post_key=%s', ('urn:li:share:222',))[0]
    assert row['publish_enabled'] == 0 and row['deleted_at'] is not None


def replace_share(old, new):
    post = sample()
    post['post_key'] = new
    post['source_url'] = post['source_url'].replace(old, new)
    return post


def test_retry_backoff_grows_and_is_capped():
    settings = Settings(token='t', retry_seconds=3600, max_retry_seconds=86400)
    worker = Sync.__new__(Sync)
    worker.settings = settings
    assert [worker.retry_delay(n) for n in (1, 2, 3, 4, 5)] == [3600, 7200, 14400, 28800, 57600]
    # Gedeckelt, damit ein dauerhaft unlesbarer Beitrag nicht ins Unendliche rutscht.
    assert worker.retry_delay(6) == 86400 and worker.retry_delay(99) == 86400
    assert worker.retry_delay(0) == 3600


def test_failed_post_backs_off_and_success_resets_the_counter(db, tmp_path):
    settings = Settings(token='t', db_host=db.conn.host, db_port=db.conn.port,
        db_password=db.conn.password, media_dir=tmp_path, retry_seconds=3600,
        max_retry_seconds=86400, refresh_days=1)
    with db.transaction():
        db.upsert_post(sample())
    reader = Mock()
    reader.read.side_effect = FetchError('Browser could not read the post')

    def attempt_state():
        row = db.rows('SELECT enrichment_attempts,enrichment_status,next_enrichment_at FROM posts WHERE post_key=%s', (KEY,))[0]
        return row['enrichment_attempts'], row['enrichment_status'], row['next_enrichment_at']

    waits = []
    for _ in range(3):
        db.execute("UPDATE posts SET next_enrichment_at='1970-01-01' WHERE post_key=%s", (KEY,))
        db.conn.commit()
        Sync(settings, db, api=Mock(), reader=reader, downloader=Mock()).enrich()
        attempts, status, due = attempt_state()
        waits.append(round((due - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 3600))
        assert status == 'failed'
    assert [a for a in waits] == [1, 2, 4], waits
    assert attempt_state()[0] == 3

    # Ein erfolgreicher Durchlauf setzt den Zähler zurück.
    reader.read.side_effect = None
    reader.read.return_value = parse_page(FIXTURE.read_text(), URL, KEY)
    db.execute("UPDATE posts SET next_enrichment_at='1970-01-01' WHERE post_key=%s", (KEY,))
    db.conn.commit()
    Sync(settings, db, api=Mock(), reader=reader, downloader=Mock(
        download=Mock(return_value={'local_path': 'a/b.jpg', 'sha256': 'x', 'content_type': 'image/jpeg', 'size_bytes': 1}))).enrich()
    attempts, status, due = attempt_state()
    assert attempts == 0 and status == 'complete'
    # Der Beispielbeitrag ist Jahre alt, die Auffrischung greift also den Deckel.
    wait_days = (due - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 86400
    assert 29 < wait_days <= 30, wait_days


def test_refresh_interval_grows_with_post_age():
    settings = Settings(token='t', refresh_days=1, max_refresh_days=30)
    worker = Sync.__new__(Sync)
    worker.settings = settings
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def days(age_days):
        return worker.refresh_delay(now - timedelta(days=age_days)) / 86400

    # Frische Beiträge behalten den kürzesten Abstand; dort ändern sich die
    # Reaktionszahlen noch.
    assert days(0) == 1 and days(7) == 1
    # Danach wächst er mit dem Alter.
    assert days(30) == 3 and days(90) == 9
    # Und ist gedeckelt, damit alte Beiträge die Warteschlange nicht fluten.
    assert days(365) == 30 and days(2600) == 30
    # Ohne Veröffentlichungsdatum bleibt es beim kürzesten Abstand.
    assert worker.refresh_delay(None) == 86400


def test_old_post_is_scheduled_far_out_after_a_successful_run(db, tmp_path):
    settings = Settings(token='t', db_host=db.conn.host, db_port=db.conn.port,
        db_password=db.conn.password, media_dir=tmp_path, refresh_days=1, max_refresh_days=30)
    old = sample()
    old['published_at'] = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=900)
    with db.transaction():
        db.upsert_post(old)
        db.execute("UPDATE posts SET next_enrichment_at='1970-01-01' WHERE post_key=%s", (KEY,))
    reader = Mock(read=Mock(return_value=parse_page(FIXTURE.read_text(), URL, KEY)))
    downloader = Mock(download=Mock(return_value={
        'local_path': 'a/b.jpg', 'sha256': 'x', 'content_type': 'image/jpeg', 'size_bytes': 1}))
    Sync(settings, db, api=Mock(), reader=reader, downloader=downloader).enrich()
    row = db.rows('SELECT enrichment_status,next_enrichment_at FROM posts WHERE post_key=%s', (KEY,))[0]
    wait_days = (row['next_enrichment_at'] - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 86400
    assert row['enrichment_status'] == 'complete'
    assert 29 < wait_days <= 30, wait_days
