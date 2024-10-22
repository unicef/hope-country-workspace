from __future__ import annotations

from functools import partial

from requests import Session

from country_workspace.sync.kobo.auth import Auth
from country_workspace.sync.kobo.data import Asset, Datum
from country_workspace.sync.kobo.raw_data import AssetListResponse, DataResponse


class URLs:
    def __init__(self, base_url) -> None:
        self._base_url = base_url

    @property
    def asset_list(self) -> str:
        return f"{self._base_url}/api/v2/assets.json"


class Client:
    def __init__(self, urls: URLs, auth: Auth) -> None:
        self.urls = urls
        self.session = Session()
        self.session.auth = auth

    @property
    def assets(self) -> tuple[Asset, ...]:
        response = self.session.get(self.urls.asset_list)
        response.raise_for_status()
        data: AssetListResponse = response.json()
        return tuple(Asset(raw, partial(self._data, raw["data"])) for raw in data["results"])

    def _data(self, url: str) -> tuple[Datum, ...]:
        response = self.session.get(url)
        response.raise_for_status()
        data: DataResponse = response.json()
        return tuple(Datum(raw) for raw in data["results"])
