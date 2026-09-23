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


def test_api_error_keeps_linkedin_wording_out_of_its_text_but_available():
    error = ApiError(404, 'No data found for this memberId', 'snapshot')
    assert error.no_data and error.endpoint == 'snapshot'
    assert error.message == 'No data found for this memberId'
    # The member-identifying wording must not reach INFO/ERROR logs via str().
    assert 'memberId' not in str(error)
    assert str(error) == 'LinkedIn API request failed (HTTP 404)'


def test_failing_request_names_the_endpoint_and_debug_logs_the_body(caplog):
    import logging
    api = LinkedInAPI('TOP_SECRET')
    response = Mock(status_code=404, text='{"message":"No data found for this memberId","status":404}')
    response.json.return_value = {'message': 'No data found for this memberId', 'status': 404}
    api.session = Mock(get=Mock(return_value=response))
    with caplog.at_level(logging.DEBUG, logger='linkedin_archiver.network'):
        with pytest.raises(ApiError) as caught:
            api.get('/rest/memberSnapshotData', {'q': 'criteria'})
    assert caught.value.endpoint == 'snapshot' and caught.value.no_data
    assert 'snapshot endpoint returned HTTP 404' in caplog.text
    assert 'TOP_SECRET' not in caplog.text


def test_changelog_endpoint_is_named_even_when_following_a_next_link():
    api = LinkedInAPI('test')
    response = Mock(status_code=404, text='{}')
    response.json.return_value = {}
    api.session = Mock(get=Mock(return_value=response))
    with pytest.raises(ApiError) as caught:
        api.get('/rest/memberChangeLogs?start=50&q=memberAndApplication')
    assert caught.value.endpoint == 'changelog'
