from typing import TypedDict

from country_workspace.sync.kobo.raw.common import ListResponse


class Submission(TypedDict):
    _id: int


class SubmissionList(ListResponse):
    results: list[Submission]
