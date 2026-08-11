from typing import Any
import re
from collections.abc import Callable, Iterable

# Matches tags like: IND-25-0000.0051
IND_TAG_RE = re.compile(r"^IND(?:-\d+)+\.\d+$")


def load_mapping_from_api(raw: dict[Any, Any], err: Callable[[str], None]) -> dict[int, str]:
    """Return validated {int: IND-tag} mapping from API payload; log invalid keys and values."""
    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            key = int(k)
        except (TypeError, ValueError):
            err(f"Invalid mapping key {k!r} -> {v!r}")
            continue
        if not isinstance(v, str) or not IND_TAG_RE.fullmatch(v):
            err(f"Invalid mapping value {k!r} -> {v!r}")
            continue
        out[key] = v
    return out


def map_role_value(
    mapping: dict[int, str],
    err: Callable[[str], None],
    hh_pk: int,
    field: str,
    value: int | str | None,
) -> str | None:
    """Map int IDs; pass-through valid IND-… tags; None stays None; else log and return None."""
    match value:
        case None:
            return None
        case int(v):
            if (m := mapping.get(v)) is None:
                err(f"HH #{hh_pk}: no mapping for {field}={v}")
            return m
        case str(s) if IND_TAG_RE.fullmatch(s):
            return s
        case _:
            err(f"HH #{hh_pk}: invalid {field}={value!r}")
            return None


def map_members(
    mapping: dict[int, str],
    err: Callable[[str], None],
    hh_pk: int,
    member_ids: Iterable[int],
) -> list[str]:
    """Return mapped member tags; log missing IDs in one message."""
    out, miss = [], []
    for mid in member_ids:
        if (m := mapping.get(mid)) is not None:
            out.append(m)
        else:
            miss.append(mid)
    if miss:
        err(f"HH #{hh_pk}: no mapping for member ids {miss}")
    return out
