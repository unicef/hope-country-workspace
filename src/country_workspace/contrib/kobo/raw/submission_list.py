from typing import TypedDict

from country_workspace.contrib.kobo.raw.common import ListResponse


class Attachment(TypedDict):
    download_url: str
    mimetype: str
    question_xpath: str


class Submission(TypedDict):
    _uuid: str
    _attachments: list[Attachment]


class SubmissionList(ListResponse):
    results: list[Submission]
