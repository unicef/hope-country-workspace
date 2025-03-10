from collections import UserDict

from country_workspace.contrib.kobo.api.data.common import Raw
from country_workspace.contrib.kobo.api.raw import submission_list as raw_submission_list
from country_workspace.contrib.kobo.api.raw.submission_list import Attachment


class Submission(Raw[raw_submission_list.Submission], UserDict):
    def __init__(self, raw: raw_submission_list.Submission) -> None:
        Raw.__init__(self, raw)

        from country_workspace.contrib.kobo.api.data.helpers import filter_out_meta_data

        UserDict.__init__(self, filter_out_meta_data(raw))

    @property
    def attachments(self) -> list[Attachment]:
        return self.raw["_attachments"]

    @property
    def id(self) -> int:
        return self._raw["_id"]
