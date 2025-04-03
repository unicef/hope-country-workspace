from collections.abc import Generator

from country_workspace.contrib.kobo.api.client.helpers import DataGetter, get_asset_list, get_asset_list_url
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
        self.url = get_asset_list_url(base_url, project_view_id, country_code)
        self.data_getter = data_getter

    @property
    def assets(self) -> Generator[Asset, None, None]:
        yield from get_asset_list(self.data_getter, self.url)
