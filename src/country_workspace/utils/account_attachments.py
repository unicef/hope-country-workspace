"""Attachments of the accounts of a record.

The **HOPE Account** Fieldset keeps them under the ``{type}_attachments`` flex
field as a list of ``{"file": <flexfile reference>}`` items, with an optional
``"title"``. The bytes and the original file name stay in `FlexFieldFile` rows
owned by the record, like any other file of the record; the push titles
attachments after that file name unless the item has a title of its own.
"""

import re
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath
from typing import Any

from country_workspace.contrib.hope.constants import (
    ACCOUNT_ATTACHMENT_TITLE_MAX_LENGTH,
    ACCOUNT_ATTACHMENTS_FIELD,
    ACCOUNT_TYPES,
)

_ATTACHMENT_QUESTION_RE = re.compile(r"^attachment_(\d+)$")


def attachment_question_index(field_name: str) -> int | None:
    """Return N for an ``attachment_N`` account question, None for any other one."""
    if match := _ATTACHMENT_QUESTION_RE.match(field_name):
        return int(match.group(1))
    return None


def attachments_field_name(account_type: str) -> str:
    return f"{account_type}_{ACCOUNT_ATTACHMENTS_FIELD}"


def attachment_title(filename: str | None) -> str:
    """Return the default title of an attachment: its file name without directories."""
    return PurePosixPath((filename or "").replace("\\", "/")).name[:ACCOUNT_ATTACHMENT_TITLE_MAX_LENGTH]


def iter_attachment_fields(flex_fields: Mapping[str, Any]) -> Iterator[tuple[str, list[Any]]]:
    for account_type in ACCOUNT_TYPES:
        name = attachments_field_name(account_type)
        if isinstance(items := flex_fields.get(name), list):
            yield name, items
