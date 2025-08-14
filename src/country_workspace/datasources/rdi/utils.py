from typing import Any
from datetime import date, datetime
from collections.abc import Generator
from contextlib import contextmanager


from country_workspace.models import AsyncJob
from country_workspace.workspaces.exceptions import BeneficiaryValidationError
from .config import Config
from .reports import generate_errors_report


def datetime_to_date(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.date()
    return v


def date_to_iso_string(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    return v


@contextmanager
def validation_errors_handler(job: AsyncJob, config: Config, **error_kwargs: Any) -> Generator[None, None, None]:
    try:
        yield
    except BeneficiaryValidationError:
        generate_errors_report(job.file, config, **error_kwargs)
        raise
