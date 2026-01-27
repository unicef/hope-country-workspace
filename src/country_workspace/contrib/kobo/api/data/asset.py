from collections.abc import Callable, Generator

from country_workspace.contrib.kobo.api.data.common import Raw
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.api.raw import asset as raw_asset


class Asset(Raw[raw_asset.Asset]):
    def __init__(
        self,
        raw: raw_asset.Asset,
        submissions: Callable[[int | None, int, Callable[[int], None] | None], Generator[Submission, None, None]],
    ) -> None:
        super().__init__(raw)
        self._submissions = submissions

    @property
    def uid(self) -> str:
        return self._raw["uid"]

    @property
    def name(self) -> str:
        return self._raw["name"]

    def submissions(
        self, min_id: int | None = None, start_page: int = 0, on_page: Callable[[int], None] | None = None
    ) -> Generator[Submission, None, None]:
        yield from self._submissions(min_id, start_page, on_page)

    def __str__(self) -> str:
        return f"Asset: {self.name}"
