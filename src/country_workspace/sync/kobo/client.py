from collections.abc import Generator, Callable
from functools import partial
from typing import cast

from requests import Session

from country_workspace.sync.kobo.auth import Auth
from country_workspace.sync.kobo.data import Asset, Datum
from country_workspace.sync.kobo.raw_data import AssetListResponse, DataResponse, Response, AssetListItem


class URLs:
    def __init__(self, base_url) -> None:
        self._base_url = base_url

    @property
    def asset_list(self) -> str:
        return f"{self._base_url}/api/v2/assets.json"


def handle_paginated_response[T, U](session: Session,
                                    url: str,
                                    collection_mapper: Callable[[Response], list[T]],
                                    item_mapper: Callable[[T], U]) -> Generator[U, None, None]:
    while url:
        response = session.get(url)
        response.raise_for_status()
        data: Response = response.json()
        yield from map(item_mapper, collection_mapper(data))
        url = data["next"]


class Client:
    def __init__(self, urls: URLs, auth: Auth) -> None:
        self.urls = urls
        self.session = Session()
        self.session.auth = auth

    @property
    def assets(self) -> Generator[Asset, None, None]:
        return handle_paginated_response(self.session,
                                         self.urls.asset_list,
                                         lambda r: cast(AssetListResponse, r)["results"],
                                         lambda i: Asset(i, partial(self._get_asset_data, i)))

    def _get_asset_data(self, raw: AssetListItem) -> Generator[Datum, None, None]:
        return handle_paginated_response(self.session,
                                         raw["data"],
                                         lambda r: cast(DataResponse, r)["results"],
                                         Datum)
