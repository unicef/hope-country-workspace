from typing import cast
from unittest.mock import Mock, call

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.client.helpers import (
    get_asset,
    get_asset_list,
    get_asset_list_url,
    has_active_deployment,
    get_raw_asset_list,
    get_raw_submission_list,
    get_submission_list,
    handle_paginated_response,
    change_url,
    get_asset_url,
    PROJECT_VIEW_ASSETS_PATH,
    ASSETS_PATH,
    SAFE_URL_CHARS,
    COUNTRY_CODE_SELECTOR,
    START_PARAMETER_NAME,
    START_PARAMETER_VALUE,
    LIMIT_PARAMETER_NAME,
    LIMIT_PARAMETER_VALUE,
    ASSET_TYPE_PARAMETER_NAME,
    ASSET_TYPE_SURVEY,
)
from country_workspace.contrib.kobo.api.data.helpers import download_attachments
from typing import TYPE_CHECKING

from country_workspace.contrib.kobo.api.data.submission import Submission

if TYPE_CHECKING:
    from country_workspace.contrib.kobo.api.raw.asset_list import Asset
    from country_workspace.contrib.kobo.api.raw.common import ListResponse

BASE_URL = "https://test.org"
PROJECT_VIEW_ID = "project-view-id"
COUNTRY_CODE = "CNT"


@pytest.mark.parametrize(
    ("url", "params", "expected_url"),
    [
        pytest.param("https://example.com", {}, "https://example.com", id="no params - no change"),
        pytest.param("https://example.com", {"path": "foo"}, "https://example.com/foo", id="path updated"),
        pytest.param(
            "https://example.com", {"query": {"foo": "bar"}}, "https://example.com?foo=bar", id="query updated"
        ),
        pytest.param(
            "https://example.com", {"query": {"q": "foo:bar"}}, "https://example.com?q=foo%3Abar", id="colon encoded"
        ),
        pytest.param(
            "https://example.com",
            {"query": {"q": "foo:bar"}, "safe": ":"},
            "https://example.com?q=foo:bar",
            id="colon left as is",
        ),
    ],
)
def test_change_url(url: str, params: dict[str, str], expected_url: str) -> None:
    assert change_url(url, **params) == expected_url


@pytest.mark.parametrize(
    ("project_view_id", "country_code"),
    [
        (PROJECT_VIEW_ID, COUNTRY_CODE),
        (None, COUNTRY_CODE),
        (PROJECT_VIEW_ID, None),
        (None, None),
    ],
)
def test_get_asset_list_url(mocker: MockerFixture, project_view_id: str | None, country_code: str | None) -> None:
    change_url_mock = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.change_url")
    expected_path = PROJECT_VIEW_ASSETS_PATH.format(project_view_id=project_view_id) if project_view_id else ASSETS_PATH
    expected_query = {ASSET_TYPE_PARAMETER_NAME: ASSET_TYPE_SURVEY}
    if country_code:
        expected_query["q"] = f"{COUNTRY_CODE_SELECTOR}:{country_code}"

    get_asset_list_url(BASE_URL, project_view_id, country_code)

    change_url_mock.assert_called_once_with(BASE_URL, path=expected_path, query=expected_query, safe=SAFE_URL_CHARS)


def test_get_asset_url(mocker: MockerFixture) -> None:
    change_url_mock = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.change_url")
    asset_id = "asset-id"
    expected_path = f"api/v2/assets/{asset_id}/"

    get_asset_url(BASE_URL, asset_id)

    change_url_mock.assert_called_once_with(BASE_URL, path=expected_path)


def test_handle_paginated_response() -> None:
    data_getter = Mock()

    response0, response1 = Mock(), Mock()
    data_getter.side_effect = response0, response1

    data0, data1 = {"next": BASE_URL}, {"next": None}
    response0.json.return_value, response1.json.return_value = data0, data1

    item0, item1 = Mock(), Mock()
    collection_mapper = Mock()
    collection_mapper.side_effect = (item0,), (item1,)

    item_mapper = Mock()
    mapped0, mapped1 = Mock(), Mock()
    item_mapper.side_effect = mapped0, mapped1

    result = tuple(handle_paginated_response(data_getter, BASE_URL, collection_mapper, item_mapper))

    response0.raise_for_status.assert_called_once()
    response1.raise_for_status.assert_called_once()
    collection_mapper.assert_has_calls((call(data0), call(data1)))
    item_mapper.assert_has_calls((call(item0), call(item1)))
    assert result == (mapped0, mapped1)


def test_has_active_deployment() -> None:
    assert has_active_deployment({"has_deployment": True}) is True
    assert has_active_deployment({"deployment__active": True}) is True
    assert has_active_deployment({"has_deployment": False, "deployment__active": False}) is False


def test_get_raw_asset_list() -> None:
    asset0 = {
        "has_deployment": True,
        "asset_type": "survey",
    }
    asset1 = {
        "deployment__active": True,
        "asset_type": "survey",
    }
    asset2 = {
        "has_deployment": False,
        "asset_type": "survey",
    }
    asset3 = {
        "has_deployment": True,
        "asset_type": "collection",
    }
    data = {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [asset0, asset1, asset2, asset3],
    }
    assert get_raw_asset_list(cast("ListResponse", data)) == [asset0, asset1, asset3]


def test_get_raw_submission_list() -> None:
    data = {"count": 0, "next": None, "previous": None, "results": (results := object())}
    assert get_raw_submission_list(cast("ListResponse", data)) == results


def test_get_asset_list(mocker: MockerFixture) -> None:
    data_getter = Mock()
    partial = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.partial")
    handle_paginated_response_mock = mocker.patch(
        "country_workspace.contrib.kobo.api.client.helpers.handle_paginated_response"
    )

    result = get_asset_list(data_getter, BASE_URL)

    assert result == handle_paginated_response_mock.return_value
    handle_paginated_response_mock.assert_called_once_with(
        data_getter, BASE_URL, get_raw_asset_list, partial.return_value
    )
    partial.assert_called_once_with(get_asset, data_getter)


@pytest.mark.parametrize(
    ("min_id", "expected_query"),
    [
        pytest.param(
            None,
            {START_PARAMETER_NAME: START_PARAMETER_VALUE, LIMIT_PARAMETER_NAME: LIMIT_PARAMETER_VALUE},
            id="without_min_id",
        ),
        pytest.param(
            12345,
            {
                START_PARAMETER_NAME: START_PARAMETER_VALUE,
                LIMIT_PARAMETER_NAME: LIMIT_PARAMETER_VALUE,
                "query": '{"_id": {"$gt": 12345}}',
            },
            id="with_min_id",
        ),
    ],
)
def test_get_submission_list(mocker: MockerFixture, min_id: int | None, expected_query: dict) -> None:
    change_url_mock = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.change_url")
    data_getter_mock = Mock()
    partial = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.partial")
    map_mock = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.map")
    handle_paginated_response_mock = mocker.patch(
        "country_workspace.contrib.kobo.api.client.helpers.handle_paginated_response"
    )
    handle_paginated_response_mock.return_value = (_item := Mock(),)

    assert get_submission_list(data_getter_mock, BASE_URL, min_id=min_id) == map_mock.return_value

    change_url_mock.assert_called_once_with(BASE_URL, query=expected_query)
    partial.assert_called_once_with(download_attachments, data_getter_mock)
    handle_paginated_response_mock.assert_called_once_with(
        data_getter_mock,
        change_url_mock.return_value,
        get_raw_submission_list,
        Submission,
    )


def test_get_asset(mocker: MockerFixture) -> None:
    asset_class = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.Asset")
    partial = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.partial")
    data_getter = Mock()
    response = data_getter.return_value
    response.json.return_value = (raw_asset_data := {"data": (data := Mock())})
    raw = {"url": BASE_URL}

    result = get_asset(data_getter, cast("Asset", raw))

    data_getter.assert_called_once_with(BASE_URL)
    response.raise_for_status.assert_called_once()
    partial.assert_called_once_with(get_submission_list, data_getter, data)
    asset_class.assert_called_once_with(raw_asset_data, partial.return_value)
    assert result == asset_class.return_value
