from typing import TypedDict


class ListResponse(TypedDict):
    count: int
    next: str | None
    previous: str | None
