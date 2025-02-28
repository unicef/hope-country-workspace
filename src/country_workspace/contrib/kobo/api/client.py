from collections.abc import Generator, Callable
from functools import partial
from typing import cast

from requests import Session, Response

from country_workspace.contrib.kobo.api.auth import Auth
from country_workspace.contrib.kobo.api.data import Submission, Asset, Question
from country_workspace.contrib.kobo.api.raw import asset_list as raw_asset_list
from country_workspace.contrib.kobo.api.raw import (
    asset as raw_asset,
    submission_list as raw_submission_list,
    common as raw_common,
)

DataGetter = Callable[[str], Response]


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
    return [
        datum
        for datum in cast(raw_asset_list.AssetList, data)["results"]
        if datum["asset_type"] == "survey" and datum["has_deployment"]
    ]


def get_raw_submission_list(data: raw_common.ListResponse) -> list[raw_submission_list.Submission]:
    return cast(raw_submission_list.SubmissionList, data)["results"]


def get_asset_list(data_getter: DataGetter, url: str) -> Generator[Asset, None, None]:
    return handle_paginated_response(data_getter, url, get_raw_asset_list, partial(get_asset, data_getter))


def get_submission_list(
    data_getter: DataGetter, url: str, questions: list[Question]
) -> Generator[Submission, None, None]:
    return handle_paginated_response(
        data_getter, url, get_raw_submission_list, partial(Submission, data_getter, questions)
    )


def get_asset(data_getter: DataGetter, raw: raw_asset_list.Asset) -> Asset:
    response = data_getter(raw["url"])
    response.raise_for_status()
    data: raw_asset.Asset = response.json()
    return Asset(data, partial(get_submission_list, data_getter, raw["data"]))


ASSET_URI = "api/v2/assets.json"
COUNTRY_CODE_SELECTOR = "settings__country_codes__contains"


class Client:
    def __init__(self, *, base_url: str, token: str, country_code: str) -> None:
        self.base_url = base_url
        self.country_code = country_code
        session = Session()
        session.auth = Auth(token)
        self.data_getter: DataGetter = session.get

    @property
    def assets(self) -> Generator[Asset, None, None]:
        url = f"{self.base_url}/{ASSET_URI}?q={COUNTRY_CODE_SELECTOR}:{self.country_code}"
        yield from get_asset_list(self.data_getter, url)
