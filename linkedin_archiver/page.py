from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from .content import clean_url, render_fragment
from .network import FetchError, PublicHttp, allowed_host, validate_url


# LinkedIns Build-CDN für die eigene Oberfläche: Sprites und Icons wie das
# «Content Credentials»-Badge, das im Bildcontainer neben dem Beitragsbild sitzt.
# Beitragsmedien liegen dagegen auf media.licdn.com. Ohne diese Abgrenzung landet
# das Badge als zweites «Bild» in der Datenbank, scheitert als SVG am Download
# und hält den Beitrag dauerhaft auf `partial`.
ASSET_HOSTS = frozenset({'static.licdn.com'})

# Vorgabe, passend zu MEDIA_ALLOWED_HOSTS. PageReader reicht die tatsächliche
# Einstellung durch.
DEFAULT_MEDIA_HOSTS = ('licdn.com', 'linkedin.com')


class PageUnavailable(FetchError):
    pass


@dataclass
class PostPage:
    text: str
    html: str
    links: list[dict]
    media: list[dict]
    fragment: str
    activity_urn: str | None
    canonical_url: str
    publicly_accessible: bool = True
    reaction_count: int | None = None
    comment_count: int | None = None
    published_at: datetime | None = None


def public_count(element):
    if element is None:
        return None
    label = element.get_text(' ', strip=True)
    match = re.search(r'\d[\d\s\u00a0\u202f.,’]*', label)
    if not match:
        return None
    # A displayed abbreviation is not an exact count; do not turn 1.2K into 12.
    if re.match(r'(?i)(?:[km]|tsd\.?|mio\.?)\b', label[match.end():].lstrip()):
        return None
    digits = re.sub(r'[^0-9]', '', match.group())
    return int(digits) if digits else None


def media_key(url: str) -> str:
    p = urlsplit(url)
    match = re.search(r'/dms/(image|video)(?:/v2)?/([^/]+)', p.path)
    stable = ':'.join(match.groups()) if match else p.netloc + p.path
    return hashlib.sha256(stable.encode()).hexdigest()


def parse_page(html: str, source_url: str, expected_key: str,
               media_hosts: tuple[str, ...] = DEFAULT_MEDIA_HOSTS) -> PostPage:
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('article.main-feed-activity-card')
    card = next((x for x in cards if expected_key in {
        x.get('data-attributed-urn'), x.get('data-activity-urn')}), None)
    # Avoid attaching another person's recommended/reposted content to this post.
    if card is None:
        raise PageUnavailable('Matching post card unavailable (login, restriction or changed markup)')
    commentary = card.select_one('[data-test-id="main-feed-activity-card__commentary"]')
    if commentary is None:
        raise PageUnavailable('Post commentary markup not found')
    safe_html, text, links = render_fragment(str(commentary), source_url)
    media, seen = [], set()

    def add(url, kind, role='attachment', alt=''):
        if not url:
            return
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname:
            return
        host = p.hostname.lower()
        if host in ASSET_HOSTS:
            return
        # Was MEDIA_ALLOWED_HOSTS ohnehin nicht herunterladen würde, wird gar
        # nicht erst als Medium angelegt: Der Eintrag würde bei jedem Versuch
        # erneut scheitern und den Beitrag dauerhaft auf `partial` halten. Ein
        # externes PDF bleibt als Link in post_links erhalten. Wer es archivieren
        # will, trägt seinen Host in MEDIA_ALLOWED_HOSTS ein — dann greift beides.
        if not allowed_host(host, media_hosts):
            return
        key = media_key(url)
        if (key, role) in seen:
            return
        seen.add((key, role))
        media.append({'media_key': key, 'source_url': url, 'kind': kind,
                      'role': role, 'alt_text': alt, 'position': len(media)})

    # Only the post's media container, never author avatars or comment images.
    for img in card.select('[data-test-id="feed-images-content"] img'):
        if img.find_parent('article') is not card:
            continue
        candidates = []
        for part in img.get('srcset', '').split(','):
            pair = part.strip().split()
            if pair and pair[0].startswith('https://'):
                try:
                    width = int(pair[1].rstrip('w')) if len(pair) > 1 else 0
                except ValueError:
                    width = 0
                candidates.append((width, pair[0]))
        url = max(candidates)[1] if candidates else img.get('data-delayed-url') or img.get('src')
        add(url, 'image', alt=img.get('alt', ''))
    for video in card.select('video'):
        if video.find_parent('article') is not card:
            continue
        add(video.get('poster'), 'image', 'poster')
        sources = [video.get('src')] + [s.get('src') for s in video.select('source')]
        try:
            encoded_sources = json.loads(video.get('data-sources', '[]'))
        except (ValueError, TypeError):
            encoded_sources = []
        if isinstance(encoded_sources, list):
            # Some public players expose the same direct URLs as JSON attributes.
            for entry in encoded_sources:
                if isinstance(entry, dict) and isinstance(entry.get('src'), str):
                    sources.append(entry['src'])
        for url in sources:
            if url:
                add(url, 'stream' if '.m3u8' in url or '.mpd' in url else 'video')
    for anchor in card.select('a[href]'):
        if anchor.find_parent('article') is not card:
            continue
        href = anchor.get('href', '')
        if urlsplit(href).path.lower().endswith('.pdf'):
            add(href, 'document', alt=anchor.get_text(strip=True))
    canonical = soup.select_one('link[rel="canonical"]')
    canonical_url = clean_url(canonical.get('href', ''), source_url) if canonical else source_url
    reaction_count = public_count(card.select_one('[data-test-id="social-actions__reaction-count"]'))
    comment_count = public_count(card.select_one('[data-test-id="social-actions__comments"]'))
    published_at = None
    # LinkedIn's structured data provides an exact publication date and counts.
    # Match its @id to this page's canonical URL before using it.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict) or data.get('@type') != 'SocialMediaPosting':
            continue
        if clean_url(data.get('@id', ''), source_url) != canonical_url:
            continue
        try:
            published_at = datetime.fromisoformat(data['datePublished'].replace('Z', '+00:00'))
            published_at = published_at.astimezone(timezone.utc).replace(tzinfo=None)
        except (KeyError, ValueError, TypeError):
            pass
        count = data.get('commentCount')
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            comment_count = count
        for stat in data.get('interactionStatistic', []):
            if not isinstance(stat, dict):
                continue
            count = stat.get('userInteractionCount')
            action = stat.get('interactionType', '')
            if (isinstance(count, int) and not isinstance(count, bool) and count >= 0
                    and isinstance(action, str) and action.endswith('/LikeAction')):
                reaction_count = count
        break
    return PostPage(text, safe_html, links, media, str(commentary),
                    card.get('data-activity-urn'),
                    canonical_url, reaction_count=reaction_count,
                    comment_count=comment_count, published_at=published_at)


class PageReader:
    def __init__(self, settings):
        self.settings = settings
        self.http = PublicHttp(settings.request_timeout)
        self.playwright = self.browser = self.context = None

    def close(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def read(self, url: str, key: str) -> PostPage:
        validate_url(url, ('linkedin.com',))
        try:
            return parse_page(self.http.html(url), url, key, self.settings.media_hosts)
        except FetchError:
            if not self.settings.browser_enabled:
                raise
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
        try:
            if self.browser is None:
                self.playwright = sync_playwright().start()
                self.browser = self.playwright.chromium.launch(headless=True)
                options = {'locale': 'en-US', 'viewport': {'width': 1280, 'height': 1600}}
                if self.settings.browser_state:
                    options['storage_state'] = self.settings.browser_state
                self.context = self.browser.new_context(**options)
                self.context.set_default_timeout(self.settings.request_timeout * 1000)

                def route(request_route):
                    u = request_route.request.url
                    if u.startswith(('data:', 'blob:')):
                        request_route.continue_()
                        return
                    try:
                        validate_url(u, ('linkedin.com', 'licdn.com'))
                        request_route.continue_()
                    except (FetchError, ValueError):
                        request_route.abort()
                self.context.route('**/*', route)
            page = self.context.new_page()
            try:
                page.goto(url, wait_until='domcontentloaded')
                selector = f'article.main-feed-activity-card[data-attributed-urn="{key}"]'
                page.locator(selector).wait_for(state='attached')
                result = parse_page(page.content(), url, key, self.settings.media_hosts)
                result.publicly_accessible = not bool(self.settings.browser_state)
                return result
            finally:
                page.close()
        except PlaywrightError as exc:
            # URLs, cookies, tokens and page content are never logged.
            raise PageUnavailable('Browser could not read the post; login/checkpoint or changed markup') from exc
