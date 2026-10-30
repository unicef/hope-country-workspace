from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from hope_flex_fields.references import DEFAULT_MIMETYPE

from country_workspace.contrib.ona.exceptions import OnaAttachmentTooLargeError, OnaNotFoundError
from country_workspace.contrib.ona.transformers import is_sys_field
from country_workspace.utils.flex_files import FlexFileContent, pending_marker

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

ATTACHMENTS_KEY = "_attachments"


def get_attachment_name(attachment: Mapping[str, Any]) -> str:
    return attachment.get("name") or PurePosixPath(attachment.get("filename") or "").name


def fetch_attachment(
    download: Callable[[str], bytes],
    attachment: Mapping[str, Any],
    *,
    submission_id: Any,
) -> FlexFileContent | None:
    """Return the file of `attachment`, or `None` when it is missing media.

    An attachment that is gone or over the size limit must not block the import
    of its submission. Any other download error propagates.
    """
    name = get_attachment_name(attachment)
    try:
        content = download(attachment["download_url"])
    except (OnaNotFoundError, OnaAttachmentTooLargeError) as exc:
        logger.warning(
            "ONA attachment skipped",
            extra={"submission_id": submission_id, "attachment": name, "reason": str(exc)},
        )
        return None
    return FlexFileContent(content=content, mimetype=attachment.get("mimetype") or DEFAULT_MIMETYPE, filename=name)


def download_attachments(
    download: Callable[[str], bytes],
    submission: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, FlexFileContent]]:
    """Download the files answered in `submission`, leaving pending markers in their place.

    ONA attachments carry no question xpath: a file question is answered with the
    attachment name, so answers are matched by value, wherever they sit in the
    submission. System fields (`_`-prefixed) are left untouched, `_attachments`
    included. Answers of a skipped attachment are emptied. Returns the marked
    submission and the bytes keyed by marker.
    """
    attachments = {
        name: attachment
        for attachment in submission.get(ATTACHMENTS_KEY) or []
        if (name := get_attachment_name(attachment)) and attachment.get("download_url")
    }
    if not attachments:
        return dict(submission), {}

    fetched: dict[str, FlexFileContent | None] = {}

    def mark(value: Any) -> Any:
        if isinstance(value, str) and (attachment := attachments.get(value)):
            if value not in fetched:
                fetched[value] = fetch_attachment(download, attachment, submission_id=submission.get("_id"))
            return pending_marker(value) if fetched[value] else ""
        if isinstance(value, Mapping):
            return mark_mapping(value)
        if isinstance(value, list):
            return [mark(item) for item in value]
        return value

    def mark_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value if is_sys_field(key) else mark(value) for key, value in data.items()}

    marked = mark_mapping(submission)
    return marked, {name: item for name, item in fetched.items() if item is not None}
