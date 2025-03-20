import logging
from typing import TYPE_CHECKING, Any

from django.db.models import Model, QuerySet

from country_workspace.models import AsyncJob, Household, Program

if TYPE_CHECKING:
    from country_workspace.models.base import Validable

logger = logging.getLogger(__name__)


def validate_queryset(queryset: QuerySet[Model], **kwargs: Any) -> dict[str, int]:
    valid = invalid = 0
    entry: "Validable"
    try:
        for __, entry in enumerate(queryset, 1):
            if entry.validate_with_checker():
                valid += 1
            else:
                invalid += 1
    except Exception as e:  # pragma: no cover
        logger.exception(e)
        raise

    return {"valid": valid, "invalid": invalid}


def validate_program(job: AsyncJob) -> dict[str, int]:
    valid = invalid = 0
    hh: Household
    try:
        p: Program = job.program
        for hh in Household.objects.filter(batch__program=p):
            if hh.validate_with_checker():
                valid += 1
            else:
                invalid += 1
    except Exception as e:  # pragma: no cover
        logger.exception(e)
        raise

    return {"valid": valid, "invalid": invalid}
