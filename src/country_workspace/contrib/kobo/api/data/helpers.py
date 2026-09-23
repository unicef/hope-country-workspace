from collections.abc import Callable
from typing import Any

from requests import Response

from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.utils.flex_files import DEFAULT_MIMETYPE, FlexFileContent, pending_marker


def filter_out_meta_data(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not key.startswith("_")}


def download_attachments(data_getter: Callable[[str], Response], submission: Submission) -> Submission:
    """Download attachment bytes, leaving a pending marker in the submission.

    The bytes are kept on `submission.files`, since the submission itself is
    stored as `raw_data` and cannot carry them.
    """
    for attachment in submission.attachments:
        xpath = attachment.get("question_xpath", "")
        if not xpath:
            continue
        response = data_getter(attachment["download_url"])
        submission.files[xpath] = FlexFileContent(
            content=response.content,
            mimetype=attachment.get("mimetype") or DEFAULT_MIMETYPE,
        )
        marker = pending_marker(xpath)
        if xpath in submission:
            submission[xpath] = marker
        else:
            parent, key = xpath.split("/", maxsplit=1)
            parent, index = parent.split("[")
            offset = int(index.rstrip("]")) - 1
            submission[parent][offset][f"{parent}/{key}"] = marker

    return submission
