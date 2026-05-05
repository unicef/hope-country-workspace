from collections.abc import Callable, Generator
from functools import partial
from typing import Final, Iterable, cast, Any
from urllib.parse import urlencode, urlparse, urlunparse

from country_workspace.contrib.kobo.api.common import DataGetter
from country_workspace.contrib.kobo.api.data.asset import Asset
from country_workspace.contrib.kobo.api.data.helpers import download_attachments
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.api.raw import (
    asset as raw_asset,
    asset_list as raw_asset_list,
    common as raw_common,
    submission_list as raw_submission_list,
)

API_ROOT: Final[str] = "api/v2"
ASSETS_PATH: Final[str] = f"{API_ROOT}/assets/"
ASSET_PATH: Final[str] = f"{API_ROOT}/assets/{{asset_id}}/"
PROJECT_VIEW_ASSETS_PATH: Final[str] = f"{API_ROOT}/project-views/{{project_view_id}}/assets/"  # last / is important
COUNTRY_CODE_SELECTOR: Final[str] = "settings__country_codes__contains"
ASSET_TYPE_PARAMETER_NAME: Final[str] = "asset_type"
ASSET_TYPE_SURVEY: Final[str] = "survey"
QUERY_PARAMETER_NAME: Final[str] = "q"
START_PARAMETER_NAME: Final[str] = "start"
START_PARAMETER_VALUE: Final[int] = 0
LIMIT_PARAMETER_NAME: Final[str] = "limit"
LIMIT_PARAMETER_VALUE: Final[int] = 10_000
EMPTY: Final[str] = ""
SAFE_URL_CHARS: Final[str] = ":"


def change_url(url: str, path: str | None = None, query: dict[str, Any] | None = None, safe: str = "") -> str:
    parsed_url = urlparse(url)

    if path:
        parsed_url = parsed_url._replace(path=path)

    if query:
        parsed_url = parsed_url._replace(query=urlencode(query, safe=safe))

    return str(urlunparse(parsed_url))


def get_asset_list_url(base_url: str, project_view_id: str | None = None, country_code: str | None = None) -> str:
    path = PROJECT_VIEW_ASSETS_PATH.format(project_view_id=project_view_id) if project_view_id else ASSETS_PATH
    query: dict[str, str] = {ASSET_TYPE_PARAMETER_NAME: ASSET_TYPE_SURVEY}
    if country_code:
        query[QUERY_PARAMETER_NAME] = f"{COUNTRY_CODE_SELECTOR}:{country_code}"

    return change_url(base_url, path=path, query=query, safe=SAFE_URL_CHARS)


def get_asset_url(base_url: str, asset_id: str) -> str:
    path = ASSET_PATH.format(asset_id=asset_id)
    return change_url(base_url, path=path)


def handle_paginated_response[T, U](
    data_getter: DataGetter,
    url: str,
    collection_mapper: Callable[[raw_common.ListResponse], list[T]],
    item_mapper: Callable[[T], U],
) -> Generator[U, None, None]:
    next_url: str | None = url
    while next_url:
        response = data_getter(next_url)
        response.raise_for_status()
        data = cast("raw_common.ListResponse", response.json())
        yield from map(item_mapper, collection_mapper(data))
        next_url = cast("str | None", data["next"])


def has_active_deployment(asset: raw_asset_list.Asset) -> bool:
    return asset.get("has_deployment") or asset.get("deployment__active", False)


def get_raw_asset_list(data: raw_common.ListResponse) -> list[raw_asset_list.Asset]:
    return [datum for datum in cast("raw_asset_list.AssetList", data)["results"] if has_active_deployment(datum)]


def get_raw_submission_list(data: raw_common.ListResponse) -> list[raw_submission_list.Submission]:
    return cast("raw_submission_list.SubmissionList", data)["results"]


def get_asset_list(data_getter: DataGetter, url: str) -> Generator[Asset, None, None]:
    return handle_paginated_response(data_getter, url, get_raw_asset_list, partial(get_asset, data_getter))


def get_submission_list(data_getter: DataGetter, url: str, min_id: int | None = None) -> Iterable[Submission]:
    import json

    query_params: dict[str, Any] = {
        START_PARAMETER_NAME: START_PARAMETER_VALUE,
        LIMIT_PARAMETER_NAME: LIMIT_PARAMETER_VALUE,
    }

    if min_id is not None:
        query_params["query"] = json.dumps({"_id": {"$gt": min_id}})

    url_with_params = change_url(url, query=query_params)
    downloader = partial(download_attachments, cast("Callable[[str], Any]", data_getter))
    return map(downloader, handle_paginated_response(data_getter, url_with_params, get_raw_submission_list, Submission))


def get_asset(data_getter: DataGetter, raw: raw_asset_list.Asset) -> Asset:
    response = data_getter(raw["url"])
    response.raise_for_status()
    raw_asset_data = cast("raw_asset.Asset", response.json())
    return Asset(raw_asset_data, partial(get_submission_list, data_getter, raw_asset_data["data"]))
