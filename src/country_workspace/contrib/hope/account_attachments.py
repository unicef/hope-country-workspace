from collections.abc import Mapping
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from hope_flex_fields.references import parse_reference

from .constants import ACCOUNT_ATTACHMENT_LIMIT, ACCOUNT_ATTACHMENT_TITLE_MAX_LENGTH

ATTACHMENT_KEYS = frozenset({"file", "title"})


class AccountAttachmentsField(forms.JSONField):
    """Attachments of one account: a list of ``{"file": <flexfile reference>, "title": <str>}`` items.

    Items without a file are dropped, so an attachment question left unanswered adds nothing.
    """

    default_error_messages = {
        "not_a_list": "Enter a list of attachments.",
        "invalid_item": 'Each attachment must be an object with a "file" and an optional "title".',
        "not_stored": "Attachment %(file)r is not a stored file.",
        "invalid_title": "Attachment titles must be text of at most %(max)d characters.",
        "too_many": "An account cannot have more than %(max)d attachments.",
    }

    def to_python(self, value: Any) -> list[dict[str, str]] | None:
        value = super().to_python(value)
        if value in self.empty_values:
            return None
        if not isinstance(value, list):
            raise ValidationError(self.error_messages["not_a_list"], code="not_a_list")
        items = [self._clean_item(item) for item in value if not (isinstance(item, Mapping) and not item.get("file"))]
        if len(items) > ACCOUNT_ATTACHMENT_LIMIT:
            raise ValidationError(
                self.error_messages["too_many"], code="too_many", params={"max": ACCOUNT_ATTACHMENT_LIMIT}
            )
        return items or None

    def _clean_item(self, item: Any) -> dict[str, str]:
        if not isinstance(item, Mapping) or not set(item) <= ATTACHMENT_KEYS:
            raise ValidationError(self.error_messages["invalid_item"], code="invalid_item")
        file, title = item["file"], item.get("title") or ""
        if parse_reference(file) is None:
            raise ValidationError(self.error_messages["not_stored"], code="not_stored", params={"file": file})
        if not isinstance(title, str) or len(title) > ACCOUNT_ATTACHMENT_TITLE_MAX_LENGTH:
            raise ValidationError(
                self.error_messages["invalid_title"],
                code="invalid_title",
                params={"max": ACCOUNT_ATTACHMENT_TITLE_MAX_LENGTH},
            )
        return {"file": file, "title": title}
