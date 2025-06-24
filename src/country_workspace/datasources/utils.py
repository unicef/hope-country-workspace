from typing import Any
from datetime import date, datetime


def datetime_to_date(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.date()
    return v


def date_to_iso_string(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    return v
