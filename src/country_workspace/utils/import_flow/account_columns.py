from __future__ import annotations

import re
from typing import Any

from country_workspace.contrib.hope.constants import ACCOUNT_TYPES

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
    ``mobile_number`` and ``mobile_financial_institution``. Any other
    ``account__{type}__*`` column is collected into the ``{type}_data`` flex
    field.

    If no ``account__{type}__*`` keys are found the row is returned unchanged.

    Raises ``AccountColumnError`` if ``{type}`` is not one of ``ACCOUNT_TYPES``.
    """
    account_keys: set[str] = set()
    direct: dict[str, Any] = {}
    extra_data: dict[str, dict[str, Any]] = {}

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
        if not _present(value):
            continue

        if field_name in _DIRECT_FIELDS:
            direct[f"{account_type}_{field_name}"] = value
        elif field_name == "data" and isinstance(value, dict):
            extra_data.setdefault(account_type, {}).update(value)
        else:
            extra_data.setdefault(account_type, {})[field_name] = value

    if not account_keys:
        return row

    result = {k: v for k, v in row.items() if k not in account_keys}
    result.update(direct)
    for account_type, data in extra_data.items():
        result[f"{account_type}_data"] = data

    return result
