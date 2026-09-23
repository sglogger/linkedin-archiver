import ipaddress
import logging
import socket
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

log = logging.getLogger(__name__)

ENDPOINTS = {'/rest/memberSnapshotData': 'snapshot', '/rest/memberChangeLogs': 'changelog'}


class FetchError(RuntimeError):
    pass


def allowed_host(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def validate_url(url: str, domains: tuple[str, ...], resolve: bool = True) -> None:
    p = urlsplit(url)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in {None, 443} or not allowed_host(p.hostname.lower(), domains)):
        raise FetchError('URL outside the permitted HTTPS hosts')
    if resolve:
        try:
            addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise FetchError('DNS lookup failed') from exc
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise FetchError('Non-public destination refused')


class PublicHttp:
    """A separate client, with no OAuth header, cookies or environment proxies."""
    def __init__(self, timeout=45):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'User-Agent': 'LinkedInPersonalArchive/0.1',
                                     'Accept-Language': 'en-US,en;q=0.9'})

    def get(self, url: str, domains: tuple[str, ...]):
        for _ in range(6):
            validate_url(url, domains)
            try:
                response = self.session.get(url, stream=True, timeout=self.timeout, allow_redirects=False)
            except requests.RequestException as exc:
                raise FetchError('Network request failed') from exc
            if response.is_redirect:
                target = urljoin(url, response.headers.get('Location', ''))
                response.close()
                url = target
                continue
            if response.status_code != 200:
                code = response.status_code
                response.close()
                raise FetchError(f'HTTP {code}')
            return response
        raise FetchError('Too many redirects')

    def html(self, url: str) -> str:
        with self.get(url, ('linkedin.com',)) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise FetchError('Page too large')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8', errors='replace')


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str = '', endpoint: str = ''):
        self.status = status
        # Kept off the exception text: LinkedIn's wording is what decides whether a
        # 404 means "nothing prepared yet", but it can name the member. DEBUG only.
        self.message = message
        self.endpoint = endpoint
        self.no_data = 'no data found for this member' in message.lower()
        description = {401: 'Token expired or invalid', 403: 'Token lacks permission',
                       429: 'LinkedIn rate limit reached'}.get(status, 'LinkedIn API request failed')
        super().__init__(f'{description} (HTTP {status})')


class LinkedInAPI:
    BASE = 'https://api.linkedin.com'

    def __init__(self, token: str, timeout=45, max_pages=10000):
        self.timeout, self.max_pages = timeout, max_pages
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'Authorization': f'Bearer {token}',
                                     'Linkedin-Version': '202312',
                                     'X-Restli-Protocol-Version': '2.0.0'})

    def get(self, path: str, params=None) -> dict:
        url = urljoin(self.BASE, path)
        p = urlsplit(url)
        if p.scheme != 'https' or p.netloc != 'api.linkedin.com' or not p.path.startswith('/rest/'):
            raise FetchError('Invalid API pagination URL')
        for attempt in range(4):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=False)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise FetchError('LinkedIn API network error') from exc
                time.sleep(2 ** attempt)
                continue
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                try:
                    delay = min(60, max(1, int(response.headers.get('Retry-After', 2 ** attempt))))
                except ValueError:
                    delay = 2 ** attempt
                response.close()
                time.sleep(delay)
                continue
            if response.status_code != 200:
                status = response.status_code
                body = response.text[:500]
                try:
                    payload = response.json()
                    message = payload.get('message', '') if isinstance(payload, dict) else ''
                except ValueError:
                    message = ''
                response.close()
                endpoint = ENDPOINTS.get(p.path, p.path)
                # The body can carry the member URN, so it stays out of INFO/ERROR logs.
                log.debug('%s endpoint returned HTTP %s: %s', endpoint, status, body)
                raise ApiError(status, message, endpoint)
            try:
                result = response.json()
            except ValueError as exc:
                raise FetchError('LinkedIn returned invalid JSON') from exc
            finally:
                response.close()
            if not isinstance(result, dict):
                raise FetchError('Unexpected LinkedIn JSON shape')
            return result
        raise FetchError('API retry limit')

    def snapshots(self):
        import hashlib
        import json
        seen = set()
        for start in range(self.max_pages):
            try:
                payload = self.get('/rest/memberSnapshotData',
                                   {'q': 'criteria', 'domain': 'MEMBER_SHARE_INFO', 'start': start})
            except ApiError as exc:
                if exc.no_data:
                    return
                raise
            elements = payload.get('elements', [])
            if isinstance(elements, dict):
                elements = [elements]
            rows = [r for e in elements for r in e.get('snapshotData', [])]
            if not rows:
                return
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            if digest in seen:
                raise FetchError('Snapshot pagination repeated a page; sync not marked complete')
            seen.add(digest)
            yield rows
            # Snapshot start is a page index, NOT an item offset. Ignore unreliable total.
        raise FetchError('MAX_API_PAGES exceeded; snapshot incomplete')

    def changes(self, start_time: int):
        import hashlib
        import json
        path = '/rest/memberChangeLogs'
        params = {'q': 'memberAndApplication', 'count': 50, 'startTime': start_time, 'start': 0}
        seen, offset = set(), 0
        for _ in range(self.max_pages):
            if params is None:
                offset = int(parse_qs(urlsplit(path).query).get('start', [offset])[0])
            payload = self.get(path, params)
            offset = int(payload.get('paging', {}).get('start', offset))
            rows = payload.get('elements', [])
            if not isinstance(rows, list):
                raise FetchError('Unexpected changelog response')
            if not rows:
                return
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            if digest in seen:
                raise FetchError('Changelog pagination repeated; checkpoint unchanged')
            seen.add(digest)
            yield rows
            next_link = next((x.get('href') for x in payload.get('paging', {}).get('links', [])
                              if x.get('rel') == 'next'), None)
            if next_link:
                path, params = next_link, None
            else:
                # A short page is not proof of exhaustion: providers can cap count.
                offset += len(rows)
                path = '/rest/memberChangeLogs'
                params = {'q': 'memberAndApplication', 'count': 50, 'startTime': start_time, 'start': offset}
        raise FetchError('MAX_API_PAGES exceeded; changelog checkpoint unchanged')
