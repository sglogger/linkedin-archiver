from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib.resources import files
import hashlib
import json

import pymysql


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Database:
    def __init__(self, settings):
        self.auto_publish = settings.auto_publish
        self.conn = pymysql.connect(host=settings.db_host, port=settings.db_port,
            user=settings.db_user, password=settings.db_password, database=settings.db_name,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
            autocommit=False, connect_timeout=15, read_timeout=60, write_timeout=60)
        with self.conn.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")

    def close(self):
        self.conn.close()

    @contextmanager
    def transaction(self):
        self.conn.begin()
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def execute(self, sql, args=()):
        with self.conn.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.rowcount

    def rows(self, sql, args=()):
        with self.conn.cursor() as cursor:
            cursor.execute(sql, args)
            return list(cursor.fetchall())

    def init(self):
        for statement in files('linkedin_archiver').joinpath('schema.sql').read_text().split(';'):
            if statement.strip():
                self.execute(statement)
        existing = {row['COLUMN_NAME'] for row in self.rows(
            'SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s',
            ('posts',))}
        for name, definition in {
            'reaction_count': 'INT UNSIGNED NULL',
            'comment_count': 'INT UNSIGNED NULL',
            'engagement_updated_at': 'DATETIME(3) NULL',
            'reshare_author': 'VARCHAR(255) NULL',
            'reshare_author_url': 'TEXT NULL',
            'reshare_text': 'LONGTEXT NULL',
            'reshare_html': 'LONGTEXT NULL',
            'enrichment_attempts': 'INT UNSIGNED NOT NULL DEFAULT 0',
        }.items():
            if name not in existing:
                self.execute(f'ALTER TABLE posts ADD COLUMN {name} {definition}')
        self.conn.commit()

    def lock(self):
        return self.rows("SELECT GET_LOCK('linkedin-personal-archive-sync', 0) AS acquired")[0]['acquired'] == 1

    def unlock(self):
        self.execute("SELECT RELEASE_LOCK('linkedin-personal-archive-sync')")

    def state(self, key, default=None):
        rows = self.rows('SELECT state_value FROM sync_state WHERE state_key=%s', (key,))
        return rows[0]['state_value'] if rows else default

    def set_state(self, key, value):
        self.execute('INSERT INTO sync_state (state_key,state_value) VALUES (%s,%s) '
                     'ON DUPLICATE KEY UPDATE state_value=VALUES(state_value)', (key, str(value)))

    def upsert_post(self, post, source='snapshot'):
        existing = self.rows('SELECT * FROM posts WHERE post_key=%s', (post['post_key'],))
        raw_column = 'raw_snapshot' if source == 'snapshot' else 'raw_event'
        text = post.get('content_text')
        if not existing:
            # AUTO_PUBLISH only ever applies to a first insert, so a post that was
            # deliberately withdrawn with `publish --disable` is never re-enabled.
            self.execute(f'''INSERT INTO posts
                (post_key,source_url,published_at,visibility,author_urn,content_text,
                 content_html,api_text,content_source,publish_enabled,{raw_column})
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (post['post_key'], post['source_url'], post.get('published_at'),
                 post.get('visibility', 'UNKNOWN'), post.get('author_urn'), text or '',
                 post.get('content_html') or '', text, source, self.auto_publish,
                 encoded(post['raw'])))
        else:
            old = existing[0]
            changed = text is not None and text != old['api_text']
            # Snapshots can lag behind events; keep already rendered page content.
            replace_content = text is not None and (old['content_source'] != 'page' or source == 'changelog' and changed)
            self.execute(f'''UPDATE posts SET {raw_column}=%s,
                published_at=COALESCE(published_at,%s), author_urn=COALESCE(%s,author_urn),
                visibility=IF(%s='UNKNOWN',visibility,%s), api_text=COALESCE(%s,api_text)
                WHERE id=%s''', (encoded(post['raw']), post.get('published_at'), post.get('author_urn'),
                    post.get('visibility', 'UNKNOWN'), post.get('visibility', 'UNKNOWN'), text, old['id']))
            if replace_content:
                self.execute('UPDATE posts SET content_text=%s,content_html=%s,content_source=%s WHERE id=%s',
                             (text, post.get('content_html') or '', source, old['id']))
                self.execute('DELETE FROM post_links WHERE post_id=%s', (old['id'],))
            if changed or source == 'changelog':
                self.execute("UPDATE posts SET next_enrichment_at=%s,enrichment_status='pending' WHERE id=%s",
                             (now(), old['id']))
        if post.get('deleted'):
            self.execute("UPDATE posts SET deleted_at=COALESCE(deleted_at,%s),publish_enabled=FALSE,"
                         "enrichment_status='deleted' WHERE post_key=%s", (now(), post['post_key']))

    def event(self, event, post):
        identity = [event.get('id'), event.get('activityId'), event.get('processedAt'), event.get('activityStatus')]
        key = hashlib.sha256(encoded(identity if any(identity) else event).encode()).hexdigest()
        if self.rows('SELECT event_key FROM post_events WHERE event_key=%s', (key,)):
            return False
        self.execute('INSERT INTO post_events (event_key,post_key,processed_at,method,payload) VALUES (%s,%s,%s,%s,%s)',
                     (key, post['post_key'], int(event.get('processedAt', 0)), event.get('method'), encoded(event)))
        self.upsert_post(post, 'changelog')
        return True

    def queue(self, limit):
        return self.rows('SELECT * FROM posts WHERE deleted_at IS NULL AND next_enrichment_at<=%s '
                         'ORDER BY next_enrichment_at,id LIMIT %s', (now(), limit))

    def save_page(self, post_id, page):
        self.execute('''UPDATE posts SET content_text=%s,content_html=%s,content_source='page',
            raw_page_fragment=%s,activity_urn=%s,canonical_url=%s,publicly_accessible=%s,
            reaction_count=COALESCE(%s,reaction_count),comment_count=COALESCE(%s,comment_count),
            engagement_updated_at=IF(%s IS NOT NULL OR %s IS NOT NULL,%s,engagement_updated_at),
            published_at=COALESCE(published_at,%s),
            reshare_author=%s,reshare_author_url=%s,reshare_text=%s,reshare_html=%s,
            enriched_at=%s,enrichment_error=NULL WHERE id=%s''',
            (page.text, page.html, page.fragment, page.activity_urn, page.canonical_url,
             page.publicly_accessible, page.reaction_count, page.comment_count,
             page.reaction_count, page.comment_count, now(), page.published_at,
             page.reshare_author, page.reshare_author_url, page.reshare_text, page.reshare_html,
             now(), post_id))
        self.execute('DELETE FROM post_links WHERE post_id=%s', (post_id,))
        for link in page.links:
            self.execute('INSERT INTO post_links (post_id,position,label,url,kind) VALUES (%s,%s,%s,%s,%s)',
                         (post_id, link['position'], link['text'], link['url'], link['kind']))
        self.execute('UPDATE post_media SET active=FALSE WHERE post_id=%s', (post_id,))
        for item in page.media:
            self.execute('''INSERT INTO post_media
                (post_id,media_key,position,kind,role,alt_text,source_url)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
                position=VALUES(position),source_url=VALUES(source_url),alt_text=VALUES(alt_text),active=TRUE''',
                (post_id, item['media_key'], item['position'], item['kind'], item['role'],
                 item['alt_text'], item['source_url']))

    def media(self, post_id):
        return self.rows('SELECT * FROM post_media WHERE post_id=%s AND active=TRUE ORDER BY position', (post_id,))

    def media_success(self, media_id, result):
        self.execute('''UPDATE post_media SET local_path=%s,sha256=%s,content_type=%s,size_bytes=%s,
            download_status='downloaded',last_error=NULL,downloaded_at=%s WHERE id=%s''',
            (result['local_path'], result['sha256'], result['content_type'], result['size_bytes'], now(), media_id))

    def media_failure(self, media_id, message):
        self.execute("UPDATE post_media SET download_status='failed',last_error=%s WHERE id=%s", (message[:255], media_id))

    def enrichment_result(self, post_id, status, delay, error=None, attempts=0):
        self.execute('UPDATE posts SET enrichment_status=%s,enrichment_error=%s,'
                     'enrichment_attempts=%s,next_enrichment_at=%s WHERE id=%s',
                     (status, error[:255] if error else None, attempts,
                      now() + timedelta(seconds=delay), post_id))

    def export(self, published_only=False, limit=None, offset=0, include_raw=False, post_key=None):
        condition = ' AND publish_enabled=TRUE' if published_only else ''
        args = ()
        if post_key is not None:
            condition += ' AND post_key=%s'
            args = (post_key,)
        fields = ('post_key,source_url,canonical_url,published_at,visibility,content_text,content_html,'
                  'content_source,publicly_accessible,publish_enabled,enrichment_status,'
                  'reaction_count,comment_count,engagement_updated_at,'
                  'reshare_author,reshare_author_url,reshare_text,reshare_html,id')
        if include_raw:
            fields += ',api_text,raw_snapshot,raw_event,raw_page_fragment,activity_urn,author_urn'
        sql = f'SELECT {fields} FROM posts WHERE deleted_at IS NULL{condition} ORDER BY published_at DESC,id DESC'
        if limit is not None:
            sql += ' LIMIT %s OFFSET %s'
            args += (limit, offset)
        posts = self.rows(sql, args)
        for post in posts:
            ident = post.pop('id')
            post['links'] = self.rows('SELECT position,label,url,kind FROM post_links WHERE post_id=%s ORDER BY position', (ident,))
            post['media'] = self.rows('SELECT position,kind,role,alt_text,source_url,local_path,content_type,sha256,'
                                     'size_bytes,download_status FROM post_media WHERE post_id=%s AND active=TRUE ORDER BY position', (ident,))
            for media in post['media']:
                media['local_url'] = '/media/' + media['local_path'] if media['local_path'] else None
            if include_raw:
                for field in ('raw_snapshot', 'raw_event'):
                    if post[field] is not None:
                        post[field] = json.loads(post[field])
        return posts

    def count_posts(self, published_only=False):
        condition = ' AND publish_enabled=TRUE' if published_only else ''
        return self.rows('SELECT COUNT(*) AS total FROM posts WHERE deleted_at IS NULL' + condition)[0]['total']

    def media_for_publication(self, local_path):
        return self.rows('''SELECT m.local_path,m.content_type,m.size_bytes FROM post_media m
            JOIN posts p ON p.id=m.post_id WHERE m.local_path=%s AND m.active=TRUE
            AND m.download_status='downloaded' AND p.publish_enabled=TRUE AND p.deleted_at IS NULL
            LIMIT 1''', (local_path,))
