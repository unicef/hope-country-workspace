from typing import NotRequired, TypedDict

from country_workspace.contrib.kobo.api.raw.common import ListResponse


class Asset(TypedDict):
    data: str
    url: str
    asset_type: str
    has_deployment: NotRequired[bool]
    deployment__active: NotRequired[bool]


class AssetList(ListResponse):
    results: list[Asset]
