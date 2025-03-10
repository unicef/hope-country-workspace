from typing import TypedDict

from country_workspace.contrib.kobo.api.raw.common import ListResponse


class Attachment(TypedDict):
    download_url: str
    mimetype: str
    question_xpath: str


class Submission(TypedDict):
    _attachments: list[Attachment]
    _id: int


class SubmissionList(ListResponse):
    results: list[Submission]
