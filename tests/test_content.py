from pathlib import Path
from datetime import datetime
import pytest

from linkedin_archiver.content import clean_url, own_post_event, render_fragment, snapshot_post
from linkedin_archiver.page import parse_page, PageUnavailable, media_key, public_count
from bs4 import BeautifulSoup

KEY = 'urn:li:share:6978966287410470912'
URL = 'https://www.linkedin.com/feed/update/' + KEY
FIXTURE = Path(__file__).parent / 'fixtures/mentions.html'


def test_preserves_mentions_hashtags_and_organization_without_guessing_people():
    result = parse_page(FIXTURE.read_text(), URL, KEY)
    assert [x['text'] for x in result.links if x['kind'] == 'person'] == [
        'Dan Rodriguez', 'Sven Decrauzat', 'Oliver Stein', 'Mike Feusi', 'Florian Kässberger']
    assert 'Tanja Veil' in result.text
    assert not any(x['text'] == 'Tanja Veil' for x in result.links)
    assert result.links[-1]['url'] == 'https://ch.linkedin.com/company/digitec-galaxus-ag'
    assert result.links[-2]['url'] == 'https://www.linkedin.com/feed/hashtag/fuckup'
    assert 'Commenter' not in result.html
    assert len(result.media) == 1
    assert result.media[0]['alt_text'] == 'Beitragsbild'
    assert result.reaction_count == 81 and result.comment_count == 7


def test_rejects_wrong_or_unavailable_post():
    for html, key in [(FIXTURE.read_text(), 'urn:li:share:1'), ('<h1>Sign in</h1>', KEY)]:
        with pytest.raises(PageUnavailable):
            parse_page(html, URL, key)


def test_html_is_safe_and_plain_text_preserves_whitespace():
    html, text, links = render_fragment('<p>Hi 😀<br><a href="javascript:alert(1)" onclick="x()">Name</a>'
                                        '<script>alert(2)</script><img onerror="x()"><a href="https://example.com">OK</a></p>', URL)
    assert 'script' not in html and 'onerror' not in html and 'onclick' not in html
    assert 'javascript' not in html
    assert text == 'Hi 😀\nNameOK'
    assert len(links) == 1


def test_no_login_links_or_offsite_login_redirects():
    assert clean_url('https://www.linkedin.com/signup/cold-join') is None
    assert clean_url('https://www.linkedin.com/login?session_redirect=https://evil.example') is None
    assert clean_url('https://user:password@example.com') is None


def test_signed_url_changes_keep_media_identity():
    a = 'https://media.licdn.com/dms/image/v2/ABC/feedshare-shrink_800/file?token=a'
    b = 'https://media.licdn.com/dms/image/v2/ABC/feedshare-shrink_1280/file?token=b'
    assert media_key(a) == media_key(b)


def test_abbreviated_social_count_is_not_reported_as_exact():
    element = BeautifulSoup('<span>1.2K reactions</span>', 'html.parser').span
    assert public_count(element) is None


def test_structured_post_data_supplies_exact_counts_and_date():
    html = FIXTURE.read_text().replace('</body>', '''<script type="application/ld+json">
    {"@type":"SocialMediaPosting","@id":"https://www.linkedin.com/posts/stevenglogger_example",
     "datePublished":"2022-09-23T06:40:26.000Z","commentCount":7,
     "interactionStatistic":[{"interactionType":"http://schema.org/LikeAction",
     "userInteractionCount":81}]}</script></body>''')
    page = parse_page(html, URL, KEY)
    assert page.published_at == datetime(2022, 9, 23, 6, 40, 26)
    assert page.reaction_count == 81 and page.comment_count == 7


def test_export_normalization_and_id():
    p = snapshot_post({'ShareLink': URL,
                       'ShareCommentary': 'Erste Zeile"\n""\n"Zweite Zeile 😀',
                       'Date': '2026-08-28 12:38:40', 'Visibility': 'MEMBER_NETWORK'})
    assert p['post_key'] == KEY
    assert p['content_text'] == 'Erste Zeile\n\nZweite Zeile 😀'
    assert p['published_at'] == datetime(2026, 8, 28, 12, 38, 40)


def test_unusable_snapshot_date_keeps_the_record():
    # A null or malformed Date must not abort the surrounding snapshot page.
    for value in (None, '', 'gestern', 12345):
        p = snapshot_post({'ShareLink': URL, 'ShareCommentary': 'Text', 'Date': value})
        assert p['post_key'] == KEY and p['published_at'] is None


def event(**values):
    return {'resourceName': 'posts', 'owner': 'urn:li:person:ME', 'actor': 'urn:li:person:ME',
            'resourceId': KEY, 'method': 'UPDATE', 'processedAt': 1000,
            'processedActivity': {'author': 'urn:li:person:ME', 'commentary': 'new 😀'}, **values}


def test_only_own_post_events_not_comments_or_other_authors():
    assert own_post_event(event())['content_text'] == 'new 😀'
    assert own_post_event(event(resourceName='comments')) is None
    assert own_post_event(event(actor='urn:li:person:THEM')) is None
    assert own_post_event(event(processedActivity={'author': 'urn:li:person:THEM'})) is None


def test_delete_and_ugc_format():
    p = own_post_event(event(method='DELETE', processedActivity={}))
    assert p['deleted'] and p['published_at'] is None
    data = {'author': 'urn:li:person:ME', 'specificContent': {
        'com.linkedin.ugc.ShareContent': {'shareCommentary': {'text': 'ugc text'}}}}
    assert own_post_event(event(resourceName='ugcPosts', resourceId='123', processedActivity=data))['post_key'] == 'urn:li:ugcPost:123'
