from typing import cast
from unittest.mock import Mock, call

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.client.helpers import (
    get_asset,
    get_asset_list,
    get_asset_list_url,
    get_raw_asset_list,
    get_raw_submission_list,
    get_submission_list,
    handle_paginated_response,
)
from country_workspace.contrib.kobo.api.data.helpers import download_attachments
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from country_workspace.contrib.kobo.api.raw.asset_list import Asset
    from country_workspace.contrib.kobo.api.raw.common import ListResponse

BASE_URL = "https://test.org"
PROJECT_VIEW_ID = "project-view-id"
COUNTRY_CODE = "CNT"


@pytest.mark.parametrize(
    ("project_view_id", "country_code"),
    [
        (PROJECT_VIEW_ID, COUNTRY_CODE),
        (None, COUNTRY_CODE),
        (PROJECT_VIEW_ID, None),
        (None, None),
    ],
)
def test_get_asset_list_url(project_view_id: str | None, country_code: str | None) -> None:
    url = get_asset_list_url(BASE_URL, project_view_id, country_code)
    assert BASE_URL in url
    assert not project_view_id or project_view_id in url
    assert not country_code or country_code in url


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


def test_get_raw_asset_list() -> None:
    asset0, asset1 = (
        {
            "has_deployment": True,
        },
        {
            "has_deployment": False,
        },
    )
    data = {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [asset0, asset1],
    }
    assert get_raw_asset_list(cast("ListResponse", data)) == [asset0]


def test_get_raw_submission_list() -> None:
    data = {"count": 0, "next": None, "previous": None, "results": (results := object())}
    assert get_raw_submission_list(cast("ListResponse", data)) == results


def test_get_asset_list(mocker: MockerFixture) -> None:
    data_getter = Mock()
    partial = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.partial")
    handle_paginated_response = mocker.patch(
        "country_workspace.contrib.kobo.api.client.helpers.handle_paginated_response"
    )

    result = get_asset_list(data_getter, BASE_URL)

    assert result == handle_paginated_response.return_value
    handle_paginated_response.assert_called_once_with(data_getter, BASE_URL, get_raw_asset_list, partial.return_value)
    partial.assert_called_once_with(get_asset, data_getter)


def test_get_submission_list(mocker: MockerFixture) -> None:
    data_getter = Mock()
    partial = mocker.patch("country_workspace.contrib.kobo.api.client.helpers.partial")
    partial.return_value.return_value = (mapped := Mock())
    handle_paginated_response = mocker.patch(
        "country_workspace.contrib.kobo.api.client.helpers.handle_paginated_response"
    )
    handle_paginated_response.return_value = (item := Mock(),)

    result = tuple(get_submission_list(data_getter, BASE_URL))

    partial.assert_called_once_with(download_attachments, data_getter)
    partial.return_value.assert_called_once_with(item)
    assert result == (mapped,)


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
