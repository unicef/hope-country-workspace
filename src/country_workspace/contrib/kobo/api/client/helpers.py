from collections.abc import Generator, Callable
from functools import partial
from typing import cast, Final, Iterable
from urllib.parse import urlparse, urlunparse

from country_workspace.contrib.kobo.api.common import DataGetter
from country_workspace.contrib.kobo.api.data.asset import Asset
from country_workspace.contrib.kobo.api.data.helpers import download_attachments
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.api.raw import (
    asset as raw_asset,
    submission_list as raw_submission_list,
    common as raw_common,
)
from country_workspace.contrib.kobo.api.raw import asset_list as raw_asset_list

API_ROOT: Final[str] = "api/v2"
ASSETS_PATH: Final[str] = f"{API_ROOT}/assets.json"
PROJECT_VIEW_ASSETS_PATH: Final[str] = f"{API_ROOT}/project-views/{{project_view_id}}/assets/"  # last / is important
COUNTRY_CODE_SELECTOR: Final[str] = "settings__country_codes__contains"
QUERY_PARAMETER_NAME: Final[str] = "q"
EMPTY: Final[str] = ""


def get_asset_list_url(base_url: str, project_view_id: str | None = None, country_code: str | None = None) -> bytes:
    parsed_url = urlparse(base_url)

    path = PROJECT_VIEW_ASSETS_PATH.format(project_view_id=project_view_id) if project_view_id else ASSETS_PATH
    query = f"{QUERY_PARAMETER_NAME}={COUNTRY_CODE_SELECTOR}:{country_code}" if country_code else EMPTY

    return urlunparse(parsed_url._replace(path=path)._replace(query=query))


def handle_paginated_response[T, U](
    data_getter: DataGetter,
    url: str,
    collection_mapper: Callable[[raw_common.ListResponse], list[T]],
    item_mapper: Callable[[T], U],
) -> Generator[U, None, None]:
    while url:
        response = data_getter(url)
        response.raise_for_status()
        data: raw_common.ListResponse = response.json()
        yield from map(item_mapper, collection_mapper(data))
        url = data["next"]


def get_raw_asset_list(data: raw_common.ListResponse) -> list[raw_asset_list.Asset]:
    return [datum for datum in cast(raw_asset_list.AssetList, data)["results"] if datum["has_deployment"]]


def get_raw_submission_list(data: raw_common.ListResponse) -> list[raw_submission_list.Submission]:
    return cast(raw_submission_list.SubmissionList, data)["results"]


def get_asset_list(data_getter: DataGetter, url: str) -> Generator[Asset, None, None]:
    return handle_paginated_response(data_getter, url, get_raw_asset_list, partial(get_asset, data_getter))


def get_submission_list(data_getter: DataGetter, url: str) -> Iterable[Submission]:
    return map(
        partial(download_attachments, data_getter),
        handle_paginated_response(data_getter, url, get_raw_submission_list, Submission),
    )


def get_asset(data_getter: DataGetter, raw: raw_asset_list.Asset) -> Asset:
    response = data_getter(raw["url"])
    response.raise_for_status()
    raw_asset_data: raw_asset.Asset = response.json()
    return Asset(raw_asset_data, partial(get_submission_list, data_getter, raw_asset_data["data"]))
