from unittest.mock import Mock
import pytest

from linkedin_archiver.network import LinkedInAPI, ApiError, FetchError, PublicHttp, validate_url


def test_snapshot_uses_page_index_and_ignores_wrong_total():
    api = LinkedInAPI('test')
    api.get = Mock(side_effect=[
        {'paging': {'total': 1}, 'elements': [{'snapshotData': [{'n': 1}]}]},
        {'paging': {'total': 1}, 'elements': [{'snapshotData': [{'n': 2}]}]},
        ApiError(404, 'No data found for this memberId')])
    assert list(api.snapshots()) == [[{'n': 1}], [{'n': 2}]]
    assert [c.args[1]['start'] for c in api.get.call_args_list] == [0, 1, 2]


def test_no_data_and_unauthorized_are_different():
    api = LinkedInAPI('test')
    api.get = Mock(side_effect=ApiError(401))
    with pytest.raises(ApiError):
        list(api.snapshots())


def test_repeated_snapshot_page_does_not_loop_or_mark_complete():
    api = LinkedInAPI('test')
    api.get = Mock(return_value={'elements': [{'snapshotData': [{'n': 1}]}]})
    with pytest.raises(FetchError, match='repeated'):
        list(api.snapshots())


def test_changelog_pagination_uses_inclusive_same_start_time():
    api = LinkedInAPI('test')
    api.get = Mock(side_effect=[{'elements': [{'id': n} for n in range(50)]},
                               {'elements': [{'id': 51}]}, {'elements': []}])
    assert len(list(api.changes(123))) == 2
    assert api.get.call_args_list[1].args[1] == {'q': 'memberAndApplication', 'count': 50, 'startTime': 123, 'start': 50}
    assert api.get.call_args_list[2].args[1]['start'] == 51


def test_short_pages_and_next_links_do_not_skip_remaining_events():
    api = LinkedInAPI('test')
    api.get = Mock(side_effect=[
        {'elements': [{'id': 1}], 'paging': {'links': [{'rel': 'next', 'href': '/rest/memberChangeLogs?start=1&q=memberAndApplication&count=50&startTime=123'}]}},
        {'elements': [{'id': 2}]}, {'elements': [{'id': 3}]}, {'elements': []}])
    assert len(list(api.changes(123))) == 3
    assert api.get.call_args_list[2].args[1]['start'] == 2


def test_api_will_not_send_token_to_pagination_host():
    api = LinkedInAPI('TOP_SECRET')
    with pytest.raises(FetchError):
        api.get('https://other.example/rest/posts')
    assert 'TOP_SECRET' not in str(ApiError(401))


@pytest.mark.parametrize('url', ['http://media.licdn.com/a', 'https://media.licdn.com.evil.example/a',
    'https://localhost/a', 'https://127.0.0.1/a', 'file:///etc/passwd',
    'https://user:secret@media.licdn.com/a', 'https://media.licdn.com:8080/a'])
def test_media_url_boundaries(url):
    with pytest.raises(FetchError):
        validate_url(url, ('licdn.com',), resolve=False)


def test_download_client_has_no_api_credentials():
    public = PublicHttp()
    assert 'Authorization' not in public.session.headers
    assert not public.session.trust_env
