from collections.abc import Generator, Callable
from typing import cast

from black.linegen import partial
from requests import Session, Response

from country_workspace.contrib.kobo.auth import Auth
from country_workspace.contrib.kobo.data import Submission, Asset, Question
from country_workspace.contrib.kobo.raw.common import ListResponse
from country_workspace.contrib.kobo.raw import asset as raw_asset, asset_list as raw_asset_list, common as raw_common
from country_workspace.contrib.kobo.raw import submission_list as raw_submission_list


DataGetter = Callable[[str], Response]


def _handle_paginated_response[T, U](data_getter: DataGetter,
                                     url: str,
                                     collection_mapper: Callable[[ListResponse], list[T]],
                                     item_mapper: Callable[[T], U]) -> Generator[U, None, None]:
    while url:
        response = data_getter(url)
        response.raise_for_status()
        data: ListResponse = response.json()
        yield from map(item_mapper, collection_mapper(data))
        url = data["next"]


def _get_raw_asset_list(data: raw_common.ListResponse) -> list[raw_asset_list.Asset]:
    return [
        datum for datum in
        cast(raw_asset_list.AssetList, data)["results"]
        if datum["asset_type"] == "survey"
    ]


def _get_raw_submission_list(data: raw_common.ListResponse) -> list[raw_submission_list.Submission]:
    return cast(raw_submission_list.SubmissionList, data)["results"]


def _get_asset_list(data_getter: DataGetter, url: str) -> Generator[Asset, None, None]:
    return _handle_paginated_response(data_getter,
                               url,
                               _get_raw_asset_list,
                               partial(_get_asset, data_getter))

def _get_submission_list(data_getter: DataGetter, url: str, questions: list[Question]) -> Generator[Submission, None, None]:
    return _handle_paginated_response(
        data_getter,
        url,
        _get_raw_submission_list,
        partial(Submission, data_getter, questions)
    )


def _get_asset(data_getter: DataGetter, raw: raw_asset_list.Asset) -> Asset:
    response = data_getter(raw["url"])
    response.raise_for_status()
    data: raw_asset.Asset = response.json()
    return Asset(data, partial(_get_submission_list, data_getter, raw["data"]))


def _get_submission() -> Submission:
    pass


class Client:
    def __init__(self, *, base_url: str, token: str) -> None:
        self.base_url = base_url
        session = Session()
        session.auth = Auth(token)
        self.data_getter: DataGetter = session.get

    @property
    def assets(self) -> Generator[Asset, None, None]:
        yield from _get_asset_list(self.data_getter, f"{self.base_url}/api/v2/assets.json")
