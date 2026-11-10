from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from country_workspace.contrib.hope.constants import ACCOUNT_TYPES
from country_workspace.utils.account_attachments import attachment_question_index, attachments_field_name

_ACCOUNT_COLUMN_RE = re.compile(r"^account__(.+?)__(.+)$")

_DIRECT_FIELDS = ("number", "financial_institution")


class AccountColumnError(ValueError):
    pass


def _present(value: Any) -> bool:
    if value is None:
        return False
    return not (isinstance(value, str) and not value.strip())


def expand_account_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Convert HOPE-style ``account__{type}__{field}`` columns to flex-field columns.

    Recognizes columns such as ``account__mobile__number`` or
    ``account__mobile__financial_institution`` and expands them into the
    prefixed flex fields expected by the **HOPE Account** Fieldset, e.g.
    ``mobile_number`` and ``mobile_financial_institution``. Numbered
    ``account__{type}__attachment_N`` columns become the ``{type}_attachments``
    list, ordered by N, each file as ``{"file": value}``. Any other
    ``account__{type}__*`` column is collected into the ``{type}_data`` flex
    field.

    If no ``account__{type}__*`` keys are found the row is returned unchanged.

    Raises ``AccountColumnError`` if ``{type}`` is not one of ``ACCOUNT_TYPES``.
    """
    account_keys: set[str] = set()
    accounts = _AccountFields()

    for key, value in row.items():
        if not isinstance(key, str):
            continue
        match = _ACCOUNT_COLUMN_RE.match(key)
        if not match:
            continue

        account_type, field_name = match.groups()
        account_keys.add(key)
        if account_type not in ACCOUNT_TYPES:
            raise AccountColumnError(
                f"Unknown account type {account_type!r} in column {key!r}. Valid types: {', '.join(ACCOUNT_TYPES)}"
            )
        if _present(value):
            accounts.add(account_type, field_name, value)

    if not account_keys:
        return row

    result = {k: v for k, v in row.items() if k not in account_keys}
    result.update(accounts.as_flex_fields())
    return result


@dataclass
class _AccountFields:
    direct: dict[str, Any] = field(default_factory=dict)
    extra_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    attachments: dict[str, list[tuple[int, Any]]] = field(default_factory=dict)

    def add(self, account_type: str, field_name: str, value: Any) -> None:
        if field_name in _DIRECT_FIELDS:
            self.direct[f"{account_type}_{field_name}"] = value
        elif (index := attachment_question_index(field_name)) is not None:
            self.attachments.setdefault(account_type, []).append((index, value))
        elif field_name == "data" and isinstance(value, dict):
            self.extra_data.setdefault(account_type, {}).update(value)
        else:
            self.extra_data.setdefault(account_type, {})[field_name] = value

    def as_flex_fields(self) -> dict[str, Any]:
        result = dict(self.direct)
        for account_type, data in self.extra_data.items():
            result[f"{account_type}_data"] = data
        for account_type, files in self.attachments.items():
            result[attachments_field_name(account_type)] = [
                {"file": value} for _index, value in sorted(files, key=lambda item: item[0])
            ]
        return result
