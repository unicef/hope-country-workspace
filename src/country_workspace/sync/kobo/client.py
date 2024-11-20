from collections.abc import Generator, Callable
from typing import cast

from black.linegen import partial
from requests import Session

from country_workspace.sync.kobo.auth import Auth
from country_workspace.sync.kobo.data import Submission, Asset, Question
from country_workspace.sync.kobo.raw.common import ListResponse
from country_workspace.sync.kobo.raw import asset as raw_asset
from country_workspace.sync.kobo.raw import asset_list as raw_asset_list
from country_workspace.sync.kobo.raw import submission_list as raw_submission_list


def handle_paginated_response[T, U](session: Session,
                                    url: str,
                                    collection_mapper: Callable[[ListResponse], list[T]],
                                    item_mapper: Callable[[T], U]) -> Generator[U, None, None]:
    while url:
        response = session.get(url)
        response.raise_for_status()
        data: ListResponse = response.json()
        yield from map(item_mapper, collection_mapper(data))
        url = data["next"]


class Client:
    def __init__(self, *, base_url: str, token: str) -> None:
        self.base_url = base_url
        self.session = Session()
        self.session.auth = Auth(token)

    @property
    def assets(self) -> Generator[Asset, None, None]:
        yield from handle_paginated_response(self.session,
                                             f"{self.base_url}/api/v2/assets.json",
                                             lambda i: cast(raw_asset_list.AssetList, i)["results"],
                                             self._get_asset_data)

    def _get_asset_data(self, raw: raw_asset_list.Asset) -> Asset:
        response = self.session.get(raw["url"])
        response.raise_for_status()
        data: raw_asset.Asset = response.json()
        return Asset(data, self._get_asset_submissions(raw["data"]))

    def _get_asset_submissions(self, url: str) -> Generator[Callable[[list[Question]], Submission], None, None]:
        return handle_paginated_response(self.session,
                                         url,
                                         lambda i: cast(raw_submission_list.SubmissionList, i)["results"],
                                         lambda i: partial(Submission, i))
