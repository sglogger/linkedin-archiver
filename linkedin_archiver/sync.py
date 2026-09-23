from datetime import datetime, timezone
import logging
import time

from .content import own_post_event, snapshot_post
from .media import MediaDownloader
from .network import LinkedInAPI
from .page import PageReader

log = logging.getLogger(__name__)


def safe_error(exc):
    # Known errors contain fixed messages, never response bodies or signed URLs.
    from .network import FetchError, ApiError
    if isinstance(exc, (FetchError, ApiError)):
        return str(exc)
    return type(exc).__name__


class Sync:
    def __init__(self, settings, db, api=None, reader=None, downloader=None):
        self.settings, self.db = settings, db
        self.api = api or LinkedInAPI(settings.token, settings.request_timeout, settings.max_pages)
        self.reader = reader or PageReader(settings)
        self.downloader = downloader or MediaDownloader(settings)

    def close(self):
        self.reader.close()

    def retry_delay(self, attempts: int) -> int:
        """Wachsender Abstand nach Fehlschlägen: 1x, 2x, 4x ... bis zur Obergrenze.

        Ein Beitrag hinter einer Login-Schranke wird eine Stunde später kaum
        lesbar sein. Mit festem Abstand belegen solche Beiträge in jedem Zyklus
        dieselben Plätze und verdrängen die Auffrischung der Reaktions- und
        Kommentarzahlen, die nur einmal täglich fällig ist.
        """
        return min(self.settings.max_retry_seconds,
                   self.settings.retry_seconds * 2 ** max(0, attempts - 1))

    def refresh_delay(self, published_at) -> int:
        """Junge Beiträge öfter auffrischen als alte.

        Reaktionen und Kommentare kommen fast nur in den ersten Tagen dazu; ein
        jahrealter Beitrag ändert sich praktisch nie mehr. Der Abstand wächst
        deshalb mit dem Alter — ein Zehntel davon, nach unten begrenzt durch
        POST_REFRESH_DAYS, nach oben durch MAX_POST_REFRESH_DAYS. Ohne bekanntes
        Veröffentlichungsdatum bleibt es beim kürzesten Abstand.
        """
        floor = self.settings.refresh_days * 86400
        ceiling = self.settings.max_refresh_days * 86400
        if published_at is None:
            return floor
        age = (datetime.now(timezone.utc).replace(tzinfo=None) - published_at).total_seconds()
        return int(min(ceiling, max(floor, age / 10)))

    def snapshot(self, force=False):
        last = float(self.db.state('last_snapshot', '0'))
        if not force and time.time() - last < self.settings.snapshot_interval:
            return
        count = 0
        for rows in self.api.snapshots():
            with self.db.transaction():
                for row in rows:
                    post = snapshot_post(row)
                    if post:
                        self.db.upsert_post(post)
                        count += 1
        if count:
            with self.db.transaction():
                self.db.set_state('last_snapshot', time.time())
        else:
            log.warning('Snapshot empty/not prepared yet; will retry next cycle')
        log.info('Snapshot: %s records processed', count)

    def changes(self):
        floor = int(time.time() * 1000) - 28 * 86400 * 1000
        saved = int(self.db.state('changelog_cursor', str(floor)))
        if saved < floor:
            log.warning('Changelog gap exceeds 28 days; historical events may be missing')
        start = max(saved, floor)
        latest, count = start, 0
        # Posts, event deduplication and cursor commit together, after ALL pages.
        with self.db.transaction():
            for events in self.api.changes(start):
                for event in events:
                    latest = max(latest, int(event.get('processedAt', start)))
                    post = own_post_event(event)
                    if post and self.db.event(event, post):
                        count += 1
            if latest > start:
                self.db.set_state('changelog_cursor', latest)  # Inclusive next request; no +1.
        log.info('Changelog: %s own-post events processed', count)

    def enrich(self, stop=None):
        if not self.settings.scrape_enabled:
            return
        queue = self.db.queue(self.settings.max_posts)
        for index, post in enumerate(queue):
            if stop and stop.is_set():
                break
            if index:
                if stop:
                    if stop.wait(self.settings.page_delay):
                        break
                else:
                    time.sleep(self.settings.page_delay)
            try:
                page = self.reader.read(post['source_url'], post['post_key'])
                with self.db.transaction():
                    self.db.save_page(post['id'], page)
                failed = 0
                for media in self.db.media(post['id']):
                    if not self.settings.media_enabled:
                        continue
                    if media['download_status'] == 'downloaded' and media['local_path'] and (
                            self.settings.media_dir / media['local_path']).is_file():
                        continue
                    try:
                        result = self.downloader.download(media)
                        with self.db.transaction():
                            self.db.media_success(media['id'], result)
                    except Exception as exc:
                        failed += 1
                        with self.db.transaction():
                            self.db.media_failure(media['id'], safe_error(exc))
                # Erfolg setzt den Zähler zurück, damit ein einmaliger Ausfall
                # den Beitrag nicht dauerhaft nach hinten schiebt.
                attempts = (post.get('enrichment_attempts') or 0) + 1 if failed else 0
                with self.db.transaction():
                    self.db.enrichment_result(post['id'], 'partial' if failed else 'complete',
                        self.retry_delay(attempts) if failed
                        else self.refresh_delay(post.get('published_at')),
                        'Some media could not be downloaded' if failed else None, attempts)
                log.info('Post %s: %s links, %s media, %s failed downloads',
                         post['post_key'], len(page.links), len(page.media), failed)
            except Exception as exc:
                message = safe_error(exc)
                attempts = (post.get('enrichment_attempts') or 0) + 1
                delay = self.retry_delay(attempts)
                with self.db.transaction():
                    self.db.enrichment_result(post['id'], 'failed', delay, message, attempts)
                log.warning('Post %s: %s (Versuch %s, naechster in %s min)',
                            post['post_key'], message, attempts, delay // 60)

    def run(self, force_snapshot=False, stop=None, api_enabled=True):
        if not self.db.lock():
            log.warning('Another worker owns the database lock; cycle skipped')
            return False
        success = True
        try:
            if api_enabled:
                # A temporarily unavailable snapshot must not stop the ongoing changelog.
                for phase, fn in (('snapshot', lambda: self.snapshot(force_snapshot)),
                                  ('changelog', self.changes)):
                    try:
                        fn()
                    except Exception as exc:
                        success = False
                        # Naming the phase covers every failure, not just ApiError.
                        log.error('API sync (%s): %s', phase, safe_error(exc))
                        log.debug('%s phase failed', phase, exc_info=True)
            self.enrich(stop)
            with self.db.transaction():
                self.db.set_state('last_cycle', datetime.now(timezone.utc).isoformat())
                self.db.set_state('last_cycle_status', 'ok' if success else 'api_error')
            return success
        finally:
            self.db.unlock()
