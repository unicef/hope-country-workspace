from typing import TypedDict, Any


class Response(TypedDict):
    count: int
    next: str | None
    previous: str | None


class AssetListItem(TypedDict):
    name: str
    data: str


class AssetListResponse(Response):
    results: list[AssetListItem]


class DataItem(TypedDict("AssetDataItem", {"formhub/uuid": str,
                                                "meta/instanceID": str})):
    __version__: str
    _attachments: list
    _geolocation: tuple[float, float] | tuple[None, None]
    _id: int
    _notes: list
    _status: Any
    _submission_time: str
    _submitted_by: str | None
    _tags: list
    _uuid: str
    _validation_status: dict
    _xform_id_string: str
    end: str
    start: str


class DataResponse(Response):
    results: list[DataItem]
