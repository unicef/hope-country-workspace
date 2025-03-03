from collections.abc import Generator
from functools import partial
from typing import Final

from country_workspace.contrib.kobo.api.client.auth import Auth
from country_workspace.contrib.kobo.api.client.helpers import DataGetter, get_asset_list, get_asset_list_url
from country_workspace.contrib.kobo.api.data.asset import Asset
from requests import Session


ACCEPT_JSON_HEADERS: Final[dict[str, str]] = {"Accept": "application/json"}


class Client:
    def __init__(
        self, *, base_url: str, token: str, country_code: str | None = None, project_view_id: str | None = None
    ) -> None:
        self.url = get_asset_list_url(base_url, project_view_id, country_code)
        session = Session()
        session.auth = Auth(token)
        self.data_getter: DataGetter = partial(session.get, headers=ACCEPT_JSON_HEADERS)

    @property
    def assets(self) -> Generator[Asset, None, None]:
        yield from get_asset_list(self.data_getter, self.url)
