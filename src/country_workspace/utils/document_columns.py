from __future__ import annotations

import re
from typing import Any

from country_workspace.contrib.hope.constants import (
    DOCUMENT_TYPES,
    MAX_DOCUMENT_COLUMNS,
)

_COLUMN_RE = re.compile(r"^document_(\d+)_(type|number|country|expire_date)$")
_ANY_DOC_COLUMN_RE = re.compile(r"^document_(\d+)_(.+)$")

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


def _collect_document_slots(row: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], set[str]]:
    slots: dict[int, dict[str, Any]] = {}
    doc_keys: set[str] = set()
    unknown_doc_keys: list[str] = []

    for key, value in row.items():
        if not isinstance(key, str):
            continue
        if (known_match := _COLUMN_RE.match(key)) is not None:
            idx, field = int(known_match.group(1)), known_match.group(2)
            slots.setdefault(idx, {})[field] = value
            doc_keys.add(key)
            continue
        if _ANY_DOC_COLUMN_RE.match(key):
            unknown_doc_keys.append(key)

    if unknown_doc_keys:
        raise DocumentColumnError(
            "Unknown document column(s): "
            f"{', '.join(sorted(unknown_doc_keys))}. "
            "Allowed suffixes are: type, number, country, expire_date."
        )

    return slots, doc_keys


def _validate_document_slot(idx: int, slot: dict[str, Any]) -> str | None:
    type_value = slot.get("type")
    has_other_values = any(_present(slot.get(field)) for field in ("number", "country", "expire_date"))

    if not _present(type_value):
        if has_other_values:
            raise DocumentColumnError(
                f"document_{idx}_type is required when other document_{idx}_* values are provided"
            )
        return None

    number_value = slot.get("number")
    country_value = slot.get("country")

    if not _present(number_value):
        raise DocumentColumnError(f"document_{idx}_number is required when document_{idx}_type is provided")
    if not _present(country_value):
        raise DocumentColumnError(f"document_{idx}_country is required when document_{idx}_type is provided")

    return _resolve_document_type(type_value)


def _apply_document_slot(result: dict[str, Any], slot: dict[str, Any], internal_type: str) -> None:
    prefix = f"{internal_type}_"
    for col_suffix, internal_suffix in _FIELD_SUFFIX_MAP.items():
        value = slot.get(col_suffix)
        if _present(value):
            result[f"{prefix}{internal_suffix}"] = value


def expand_document_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Convert numbered document columns to type-prefixed flex-field columns.

    Recognizes ``document_X_type``, ``document_X_number``,
    ``document_X_country`` and the optional ``document_X_expire_date``
    where *X* is 1..MAX_DOCUMENT_COLUMNS.  Each populated triplet is
    expanded into ``{type}_document_number``, ``{type}_country`` and
    (optionally) ``{type}_expiry_date``.

    If no ``document_X_*`` keys are found the row is returned unchanged.
    """
    slots, doc_keys = _collect_document_slots(row)

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
        internal_type = _validate_document_slot(idx, slots[idx])
        if internal_type is None:
            continue
        _apply_document_slot(result, slots[idx], internal_type)

    return result
