from typing import TypedDict

from country_workspace.contrib.kobo.raw.common import ListResponse


class Submission(TypedDict):
    _uuid: str


class SubmissionList(ListResponse):
    results: list[Submission]
