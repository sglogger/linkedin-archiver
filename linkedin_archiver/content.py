"""Normalization and conservative rendering; never infer a person's profile URL."""
from datetime import datetime, timezone
from html import escape
import hashlib
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit, unquote

from bs4 import BeautifulSoup, NavigableString, Tag


POST_URN = re.compile(r"urn:li:(share|ugcPost|activity):\d+")


def post_identity(value: str) -> str:
    match = POST_URN.search(unquote(value))
    if match:
        return match.group()
    return "url:" + hashlib.sha256(value.encode()).hexdigest()


def post_url(urn: str) -> str:
    from urllib.parse import quote
    return "https://www.linkedin.com/feed/update/" + quote(urn, safe="")


def clean_url(value: str, base: str = "https://www.linkedin.com", depth: int = 0) -> str | None:
    if depth > 2 or not value:
        return None
    value = urljoin(base, value.strip())
    p = urlsplit(value)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        return None
    if any(ord(c) < 32 for c in value):
        return None
    if p.hostname == "linkedin.com" or p.hostname.endswith(".linkedin.com"):
        if p.path == "/redir/redirect":
            # LinkedIns Klickzähler. Das eigentliche Ziel steht im url-Parameter
            # und ist bewusst extern — anders als bei den Anmeldelinks unten.
            target = parse_qs(p.query).get("url", [None])[0]
            return clean_url(target, base, depth + 1) if target else None
        if p.path in {"/signup/cold-join", "/login", "/authwall"}:
            redirect = parse_qs(p.query).get("session_redirect", [None])[0]
            # Do not preserve a login link in place of a mention.
            if not redirect:
                return None
            target = clean_url(redirect, base, depth + 1)
            if not target:
                return None
            host = urlsplit(target).hostname or ""
            return target if host == "linkedin.com" or host.endswith(".linkedin.com") else None
        query = urlencode([(k, v) for k, v in parse_qsl(p.query)
                           if k not in {"trk", "trackingId", "lipi", "originalSubdomain"}
                           and not k.startswith("utm_")])
        return urlunsplit((p.scheme, p.netloc, p.path, query, p.fragment))
    return value


def link_kind(url: str) -> str:
    p = urlsplit(url)
    if p.hostname and (p.hostname == "linkedin.com" or p.hostname.endswith(".linkedin.com")):
        if p.path.startswith("/in/"):
            return "person"
        if p.path.startswith("/company/"):
            return "organization"
        if "/hashtag/" in p.path:
            return "hashtag"
    return "external"


def render_fragment(fragment: str, base: str) -> tuple[str, str, list[dict]]:
    soup = BeautifulSoup(fragment, "html.parser")
    for node in soup.select("script,style,iframe,object,svg,form,button,noscript"):
        node.decompose()
    links = []
    plain = []

    def render(node):
        if isinstance(node, NavigableString):
            plain.append(str(node))
            return escape(str(node))
        if not isinstance(node, Tag):
            return ""
        if node.name == "br":
            plain.append("\n")
            return "<br>"
        children = "".join(render(c) for c in node.children)
        if node.name == "a":
            href = clean_url(node.get("href", ""), base)
            if href:
                links.append({"position": len(links), "text": node.get_text(),
                              "url": href, "kind": link_kind(href)})
                return f'<a href="{escape(href, quote=True)}" rel="noopener noreferrer">{children}</a>'
        if node.name in {"p", "div", "li", "blockquote", "h1", "h2", "h3"}:
            plain.append("\n")
            return f"<p>{children}</p>"
        if node.name in {"strong", "em", "b", "i", "u"}:
            return f"<{node.name}>{children}</{node.name}>"
        return children

    html = "".join(render(c) for c in soup.contents).strip()
    return html, "".join(plain).strip(), links


def text_html(value: str) -> str:
    return "<p>" + escape(value).replace("\n", "<br>") + "</p>"


def snapshot_text(value: str) -> str:
    # The actual export sometimes wraps every line in CSV-style quotes.
    if '\"\n\"' in value:
        value = value.replace('\"\n\"', '\n').strip('"')
    return value


def snapshot_post(row: dict) -> dict | None:
    url = clean_url(row.get("ShareLink", ""))
    if not url or not POST_URN.search(unquote(url)):
        return None
    text = snapshot_text(row.get("ShareCommentary", ""))
    date = None
    try:
        # A null/absent Date must not abort the whole snapshot page.
        date = datetime.strptime(row.get("Date", ""), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        pass
    return {"post_key": post_identity(url), "source_url": url,
            "content_text": text, "content_html": text_html(text),
            "published_at": date, "visibility": row.get("Visibility", "UNKNOWN"),
            "raw": row}


def own_post_event(event: dict) -> dict | None:
    resource = event.get("resourceName", "").lower()
    if resource not in {"posts", "shares", "ugcposts"}:
        return None  # Never import a commented/liked third-party post as an own post.
    actor, owner = event.get("actor"), event.get("owner")
    if not owner or actor != owner:
        return None
    data = event.get("processedActivity") or event.get("activity") or {}
    if not isinstance(data, dict):
        data = {}
    author = data.get("author", data.get("owner"))
    if author and author != owner:
        return None
    raw_id = str(event.get("resourceId") or data.get("id") or "")
    match = POST_URN.fullmatch(raw_id)
    if not match:
        if raw_id.isdigit() and resource in {"shares", "ugcposts"}:
            raw_id = f"urn:li:{'share' if resource == 'shares' else 'ugcPost'}:{raw_id}"
        else:
            return None
    text = data.get("commentary")
    if isinstance(text, dict):
        text = text.get("text")
    if text is None:
        text = data.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {}).get("shareCommentary", {}).get("text")
    if text is None:
        raw_text = data.get("text")
        text = raw_text.get("text") if isinstance(raw_text, dict) else raw_text
    visibility = data.get("visibility", "UNKNOWN")
    if isinstance(visibility, dict):
        visibility = next(iter(visibility.values()), "UNKNOWN")
    stamp = data.get("publishedAt") or data.get("createdAt")
    # An edit's capturedAt is not the publication time.
    if stamp is None and event.get("method") == "CREATE":
        stamp = event.get("capturedAt")
    date = datetime.fromtimestamp(stamp / 1000, timezone.utc).replace(tzinfo=None) if isinstance(stamp, (int, float)) else None
    return {"post_key": raw_id, "source_url": post_url(raw_id),
            "content_text": text if isinstance(text, str) else None,
            "content_html": text_html(text) if isinstance(text, str) else None,
            "published_at": date, "visibility": visibility,
            "author_urn": owner, "raw": event,
            "deleted": event.get("method") == "DELETE"}

