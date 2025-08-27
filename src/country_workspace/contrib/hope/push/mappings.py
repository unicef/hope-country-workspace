from collections.abc import Callable, Iterable

from .config import IND_TAG_RE


def load_mapping_from_api(raw: dict, err: Callable[[str], None]) -> dict[int, str]:
    """Return {int: str} mapping from API payload; log keys that cannot be coerced to int."""
    out = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            err(f"Invalid mapping key '{k}' -> '{v}'")
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
