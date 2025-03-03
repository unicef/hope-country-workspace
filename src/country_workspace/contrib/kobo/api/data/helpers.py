from base64 import b64encode
from collections.abc import Callable
from typing import Any

from country_workspace.contrib.kobo.api.data.submission import Submission
from requests import Response


def filter_out_meta_data(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not key.startswith("_")}


def download_attachments(data_getter: Callable[[str], Response], submission: Submission) -> Submission:
    for attachment in submission.attachments:
        content = b64encode(data_getter(attachment["download_url"]).content).decode()
        value = f"data:{attachment['mimetype']};base64,{content}"
        key = attachment["question_xpath"]
        if key in submission:
            submission[key] = value
        elif key:
            parent, key = key.split("/", maxsplit=1)
            parent, index = parent.split("[")
            index = int(index.rstrip("]")) - 1
            submission[parent][index][f"{parent}/{key}"] = value

    return submission
