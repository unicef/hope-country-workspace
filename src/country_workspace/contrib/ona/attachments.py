from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from hope_flex_fields.references import DEFAULT_MIMETYPE

from country_workspace.contrib.ona.transformers import is_sys_field
from country_workspace.utils.flex_files import FlexFileContent, pending_marker

if TYPE_CHECKING:
    from collections.abc import Callable

ATTACHMENTS_KEY = "_attachments"


def get_attachment_name(attachment: Mapping[str, Any]) -> str:
    return attachment.get("name") or PurePosixPath(attachment.get("filename") or "").name


def download_attachments(
    download: Callable[[str], bytes],
    submission: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, FlexFileContent]]:
    """Download the files answered in `submission`, leaving pending markers in their place.

    ONA attachments carry no question xpath: a file question is answered with the
    attachment name, so answers are matched by value, wherever they sit in the
    submission. System fields (`_`-prefixed) are left untouched, `_attachments`
    included. Returns the marked submission and the bytes keyed by marker.
    """
    attachments = {
        name: attachment
        for attachment in submission.get(ATTACHMENTS_KEY) or []
        if (name := get_attachment_name(attachment)) and attachment.get("download_url")
    }
    files: dict[str, FlexFileContent] = {}
    if not attachments:
        return dict(submission), files

    def mark(value: Any) -> Any:
        if isinstance(value, str) and (attachment := attachments.get(value)):
            if value not in files:
                files[value] = FlexFileContent(
                    content=download(attachment["download_url"]),
                    mimetype=attachment.get("mimetype") or DEFAULT_MIMETYPE,
                    filename=value,
                )
            return pending_marker(value)
        if isinstance(value, Mapping):
            return mark_mapping(value)
        if isinstance(value, list):
            return [mark(item) for item in value]
        return value

    def mark_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value if is_sys_field(key) else mark(value) for key, value in data.items()}

    return mark_mapping(submission), files
