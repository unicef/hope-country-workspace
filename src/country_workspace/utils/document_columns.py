from __future__ import annotations

import re
from typing import Any

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES, MAX_DOCUMENT_COLUMNS

_COLUMN_RE = re.compile(r"^document_(\d+)_(type|number|country|expire_date)$")

_NORMALIZED_TYPES: dict[str, str] = {key: t for t in DOCUMENT_TYPES for key in (t, t.replace("_", " "))}

_FIELD_SUFFIX_MAP = {
    "number": "document_number",
    "country": "country",
    "expire_date": "expiry_date",
}


class DocumentColumnError(ValueError):
    pass


def _resolve_document_type(raw_value: Any) -> str:
    if not raw_value or not isinstance(raw_value, str) or not raw_value.strip():
        raise DocumentColumnError(f"Invalid document type: {raw_value}")
    key = raw_value.strip().lower().replace("-", "_").replace("_", " ").strip()
    key = re.sub(r"\s+", " ", key)
    if key in _NORMALIZED_TYPES:
        return _NORMALIZED_TYPES[key]
    normalized_underscore = key.replace(" ", "_")
    if normalized_underscore in _NORMALIZED_TYPES:
        return _NORMALIZED_TYPES[normalized_underscore]
    raise DocumentColumnError(f"Unknown document type: {raw_value!r}. Valid types: {', '.join(DOCUMENT_TYPES)}")


def _present(value: Any) -> bool:
    if value is None:
        return False
    return not (isinstance(value, str) and not value.strip())


def expand_document_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Convert numbered document columns to type-prefixed flex-field columns.

    Recognizes ``document_X_type``, ``document_X_number``,
    ``document_X_country`` and the optional ``document_X_expire_date``
    where *X* is 1..MAX_DOCUMENT_COLUMNS.  Each populated triplet is
    expanded into ``{type}_document_number``, ``{type}_country`` and
    (optionally) ``{type}_expiry_date``.

    If no ``document_X_*`` keys are found the row is returned unchanged.
    """
    slots: dict[int, dict[str, Any]] = {}
    doc_keys: set[str] = set()

    for key in list(row.keys()):
        match = _COLUMN_RE.match(key)
        if not match:
            continue
        idx, field = int(match.group(1)), match.group(2)
        slots.setdefault(idx, {})[field] = row[key]
        doc_keys.add(key)

    if not slots:
        return row

    max_idx = max(slots)
    if max_idx > MAX_DOCUMENT_COLUMNS:
        raise DocumentColumnError(
            f"Document index {max_idx} exceeds maximum of {MAX_DOCUMENT_COLUMNS}. "
            f"Only document_1 through document_{MAX_DOCUMENT_COLUMNS} are allowed."
        )

    result = {k: v for k, v in row.items() if k not in doc_keys}

    for idx in sorted(slots):
        slot = slots[idx]
        type_value = slot.get("type")

        if not _present(type_value):
            continue

        internal_type = _resolve_document_type(type_value)
        prefix = f"{internal_type}_"

        number_value = slot.get("number")
        country_value = slot.get("country")

        if not _present(number_value) or not _present(country_value):
            raise DocumentColumnError(
                f"document_{idx}_number and document_{idx}_country are required when document_{idx}_type is provided"
            )

        for col_suffix, internal_suffix in _FIELD_SUFFIX_MAP.items():
            value = slot.get(col_suffix)
            if _present(value):
                result[f"{prefix}{internal_suffix}"] = value

    return result
