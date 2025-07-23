import logging
from typing import Any

from django.db.models import Model, QuerySet

from country_workspace.models import AsyncJob
from country_workspace.state import state


logger = logging.getLogger(__name__)


def validate_queryset(queryset: QuerySet[Model], **kwargs: Any) -> dict[str, int]:
    total = {"valid": 0, "invalid": 0}

    try:
        program = queryset.first().program
        with state.set(tenant=program.country_office, program=program):
            for entry in queryset:
                is_valid = entry.validate_with_checker()
                total["valid" if is_valid else "invalid"] += 1

    except Exception as e:  # pragma: no cover
        logger.error("Error during queryset validation: %s", e)
        raise

    return total


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
