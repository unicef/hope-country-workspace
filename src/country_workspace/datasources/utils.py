from typing import Any
from datetime import date


def strip_time_iso(v: Any) -> Any:
    if not isinstance(v, str):
        return v
    date_part = v.split(" ", 1)[0]
    try:
        d = date.fromisoformat(date_part)
        return d.isoformat()
    except ValueError:
        return v
