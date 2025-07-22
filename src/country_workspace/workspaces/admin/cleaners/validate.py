import logging
from typing import TYPE_CHECKING, Any

from django.db.models import Model, QuerySet

from country_workspace.models import AsyncJob
from country_workspace.state import state

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
        logger.error(e)
        raise

    return {"valid": valid, "invalid": invalid}


def validate_program(job: AsyncJob) -> dict[str, int]:
    total = {"valid": 0, "invalid": 0}

    try:
        program = job.program
        with state.set(tenant=program.country_office, program=program):
            qs = program.households if program.beneficiary_group.master_detail else program.individuals
            for beneficiary in qs:
                is_valid = beneficiary.validate_with_checker()
                total["valid" if is_valid else "invalid"] += 1
    except Exception as e:
        logger.error("Error during program validation: %s", e)
        raise

    return total
