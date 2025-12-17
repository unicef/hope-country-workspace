from collections.abc import Generator
from functools import partial

from country_workspace.contrib.kobo.api.client.helpers import (
    DataGetter,
    get_asset_list,
    get_asset_list_url,
    get_submission_list,
    get_asset_url,
)
from country_workspace.contrib.kobo.api.data.asset import Asset


class Client:
    def __init__(
        self,
        *,
        data_getter: DataGetter,
        base_url: str,
        country_code: str | None = None,
        project_view_id: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.country_code = country_code
        self.project_view_id = project_view_id
        self.data_getter = data_getter

    @property
    def assets(self) -> Generator[Asset, None, None]:
        url = get_asset_list_url(self.base_url, self.project_view_id, self.country_code)
        yield from get_asset_list(self.data_getter, url)

    def get_asset(self, asset_id: str) -> Asset:
        url = get_asset_url(self.base_url, asset_id)
        response = self.data_getter(url)
        response.raise_for_status()
        raw_asset = response.json()
        return Asset(raw_asset, partial(get_submission_list, self.data_getter, raw_asset["data"]))
