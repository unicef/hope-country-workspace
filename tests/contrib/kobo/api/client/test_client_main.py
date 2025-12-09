from unittest.mock import Mock

from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.client.main import Client


def test_client_assets(mocker: MockerFixture) -> None:
    data_getter_mock = Mock()
    get_asset_list_url = mocker.patch("country_workspace.contrib.kobo.api.client.main.get_asset_list_url")
    url = get_asset_list_url.return_value
    get_asset_list = mocker.patch("country_workspace.contrib.kobo.api.client.main.get_asset_list")
    get_asset_list.return_value = []

    tuple(
        Client(
            data_getter=data_getter_mock,
            base_url=(base_url := "https://test.org"),
            country_code=(country_code := "CNT"),
            project_view_id=(project_view_id := "project-view-id"),
        ).assets
    )

    get_asset_list_url.assert_called_once_with(base_url, project_view_id, country_code)
    get_asset_list.assert_called_with(data_getter_mock, url)


def test_client_get_asset(mocker: MockerFixture) -> None:
    data_getter_mock = Mock()
    response_mock = data_getter_mock.return_value
    response_mock.json.return_value = {"data": "submissions-url"}
    get_asset_url = mocker.patch("country_workspace.contrib.kobo.api.client.main.get_asset_url")
    url = get_asset_url.return_value

    asset_id = "asset-id"
    Client(
        data_getter=data_getter_mock,
        base_url=(base_url := "https://test.org"),
    ).get_asset(asset_id)

    get_asset_url.assert_called_once_with(base_url, asset_id)
    data_getter_mock.assert_called_with(url)
