from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.client.main import ACCEPT_JSON_HEADERS, Client


def test_client(mocker: MockerFixture) -> None:
    session_class = mocker.patch("country_workspace.contrib.kobo.api.client.main.Session")
    session = session_class.return_value
    auth_class = mocker.patch("country_workspace.contrib.kobo.api.client.main.Auth")
    auth = auth_class.return_value
    partial = mocker.patch("country_workspace.contrib.kobo.api.client.main.partial")
    data_getter = partial.return_value
    get_asset_list_url = mocker.patch("country_workspace.contrib.kobo.api.client.main.get_asset_list_url")
    url = get_asset_list_url.return_value
    get_asset_list = mocker.patch("country_workspace.contrib.kobo.api.client.main.get_asset_list")
    get_asset_list.return_value = []

    tuple(
        Client(
            base_url=(base_url := "https://test.org"),
            token=(token := "test-token"),
            country_code=(country_code := "CNT"),
            project_view_id=(project_view_id := "project-view-id"),
        ).assets
    )

    get_asset_list_url.assert_called_once_with(base_url, project_view_id, country_code)
    session_class.assert_called_once()
    auth_class.assert_called_once_with(token)
    assert session.auth == auth
    partial.assert_called_once_with(session.get, headers=ACCEPT_JSON_HEADERS)
    get_asset_list.assert_called_with(data_getter, url)
