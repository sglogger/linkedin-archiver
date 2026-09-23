from pathlib import Path
from datetime import datetime
import pytest

from urllib.parse import urlsplit

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


def test_linkedin_ui_icons_are_not_collected_as_post_media():
    # static.licdn.com liefert das «Content Credentials»-Badge, das im
    # Bildcontainer neben dem echten Beitragsbild sitzt.
    html = f'''<article class="main-feed-activity-card" data-attributed-urn="{KEY}">
      <div data-test-id="main-feed-activity-card__commentary">Text</div>
      <div data-test-id="feed-images-content">
        <img src="https://media.licdn.com/dms/image/v2/ABC/feedshare-shrink_800/0/x.jpg" alt="Foto">
        <img src="https://static.licdn.com/aero-v1/sc/h/dur0ryw0e9uscxa9b6zqvgvfs" alt="">
      </div>
    </article>'''
    page = parse_page(html, URL, KEY)
    hosts = [urlsplit(m['source_url']).hostname for m in page.media]
    assert hosts == ['media.licdn.com'], hosts
    assert page.media[0]['position'] == 0


def page_with(extra):
    return f'''<article class="main-feed-activity-card" data-attributed-urn="{KEY}">
      <div data-test-id="main-feed-activity-card__commentary">Text {extra}</div>
      <div data-test-id="feed-images-content">
        <img src="https://media.licdn.com/dms/image/v2/ABC/feedshare-shrink_800/0/x.jpg" alt="Foto">
      </div>
      {extra}
    </article>'''


def test_external_document_stays_a_link_and_is_not_queued_for_download():
    # Ein PDF auf einem fremden Host würde MEDIA_ALLOWED_HOSTS ohnehin ablehnen.
    # Es darf deshalb gar nicht erst als Medium entstehen, sonst scheitert es bei
    # jedem Durchlauf erneut und hält den Beitrag auf `partial`.
    anchor = '<a href="https://www.sbs.ox.ac.uk/sites/default/files/report.pdf">Report</a>'
    page = parse_page(page_with(anchor), URL, KEY)
    assert [m['kind'] for m in page.media] == ['image']
    assert any(l['url'].startswith('https://www.sbs.ox.ac.uk/') for l in page.links)


def test_document_host_added_to_media_allowed_hosts_is_archived():
    anchor = '<a href="https://www.sbs.ox.ac.uk/sites/default/files/report.pdf">Report</a>'
    page = parse_page(page_with(anchor), URL, KEY,
                      ('licdn.com', 'linkedin.com', 'sbs.ox.ac.uk'))
    assert [m['kind'] for m in page.media] == ['image', 'document']
    assert page.media[1]['source_url'].endswith('report.pdf')


RESHARE = Path(__file__).parent / 'fixtures/reshare.html'
RESHARE_KEY = 'urn:li:ugcPost:7498798815765000192'
RESHARE_URL = 'https://www.linkedin.com/feed/update/urn%3Ali%3AugcPost%3A7498798815765000192'


def test_repost_keeps_the_shared_posts_media():
    # Der geteilte Beitrag liegt in einem verschachtelten <article class="…
    # feed-reshare-content">. Sein Video IST der Inhalt des Reposts.
    page = parse_page(RESHARE.read_text(), RESHARE_URL, RESHARE_KEY)
    kinds = [m['kind'] for m in page.media]
    assert 'video' in kinds, kinds
    assert 'image' in kinds, 'Vorschaubild aus data-poster-url fehlt'


def test_repost_records_the_original_author_and_text():
    page = parse_page(RESHARE.read_text(), RESHARE_URL, RESHARE_KEY)
    assert page.reshare_author == 'Andreas Ott'
    assert page.reshare_author_url == 'https://ch.linkedin.com/in/andreas-ott-46284896'
    assert 'VoIP' in (page.reshare_text or '')
    # Der eigene Kommentar darf nicht mit dem geteilten Text vermischt werden.
    assert 'VoIP' not in page.text
    assert 'ex-Kollegen' in page.text


def test_only_the_highest_video_bitrate_is_archived():
    # LinkedIn bietet dieselbe Aufnahme als 640p und 720p an.
    page = parse_page(RESHARE.read_text(), RESHARE_URL, RESHARE_KEY)
    videos = [m['source_url'] for m in page.media if m['kind'] == 'video']
    assert len(videos) == 1, videos
    assert '720p' in videos[0]


def test_video_identity_survives_a_bitrate_change():
    a = 'https://dms.licdn.com/playlist/vid/v2/D4E05AQFMJDicACYCsg/mp4-640p-30fp-crf28/x/1?e=1'
    b = 'https://dms.licdn.com/playlist/vid/v2/D4E05AQFMJDicACYCsg/mp4-720p-30fp-crf28/y/2?e=2'
    assert media_key(a) == media_key(b)


def test_a_plain_post_reports_no_reshare():
    page = parse_page(FIXTURE.read_text(), URL, KEY)
    assert page.reshare_author is None and page.reshare_html is None


ARTICLE = Path(__file__).parent / 'fixtures/article-share.html'
ARTICLE_KEY = 'urn:li:share:6382931760497389568'
ARTICLE_URL = 'https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A6382931760497389568'


def test_link_share_without_own_text_is_not_a_failure():
    # Ein geteilter Artikel ohne Kommentar hat kein commentary-Element. Früher
    # galt das als Fehler und der Beitrag wurde in jedem Zyklus neu versucht,
    # ohne je gelingen zu können.
    page = parse_page(ARTICLE.read_text(), ARTICLE_URL, ARTICLE_KEY)
    assert page.text == '' and page.html == ''


def test_link_share_keeps_target_title_and_preview():
    page = parse_page(ARTICLE.read_text(), ARTICLE_URL, ARTICLE_KEY)
    assert [l['url'] for l in page.links] == [
        'https://www.youracclaim.com/badges/e400771c-6afd-464b-a664-2eacc88dfc8b']
    assert page.links[0]['text'].startswith('Stress-Tolerant')
    assert page.links[0]['kind'] == 'external'
    # Das Vorschaubild liegt ausserhalb von feed-images-content.
    assert [(m['kind'], m['role']) for m in page.media] == [('image', 'preview')]


def test_linkedin_click_redirect_is_unwrapped_to_the_real_target():
    wrapped = ('https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fexample%2Ecom%2Fa'
               '&urlhash=phjs&trk=pub')
    assert clean_url(wrapped) == 'https://example.com/a'
    # Ohne Ziel bleibt nichts übrig, statt den Zähler-Link zu archivieren.
    assert clean_url('https://www.linkedin.com/redir/redirect?urlhash=x') is None


def test_a_post_with_text_is_unaffected():
    page = parse_page(FIXTURE.read_text(), URL, KEY)
    assert page.text and page.html and page.fragment
