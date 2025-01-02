from typing import TypedDict

from country_workspace.contrib.kobo.api.raw.common import ListResponse


class Asset(TypedDict):
    data: str
    url: str
    asset_type: str


class AssetList(ListResponse):
    results: list[Asset]
