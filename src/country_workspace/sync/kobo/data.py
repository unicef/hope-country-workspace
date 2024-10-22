from collections.abc import Callable

from country_workspace.sync.kobo.raw_data import AssetListItem, DataItem


class Datum:
    def __init__(self, raw: DataItem) -> None:
        self._raw = raw


class Asset:
    def __init__(self, raw: AssetListItem, data_thunk: Callable[[], tuple[Datum, ...]]) -> None:
        self._raw = raw
        self._data_thunk = data_thunk

    @property
    def data(self) -> tuple[Datum, ...]:
        return self._data_thunk()
