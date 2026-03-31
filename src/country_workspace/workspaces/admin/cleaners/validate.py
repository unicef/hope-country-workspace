import logging
from typing import Any
from itertools import batched
from collections.abc import Iterable

from concurrency.utils import fqn
from constance import config
from django.db.models import Model, QuerySet, Prefetch
from django.db.models.query import prefetch_related_objects
from django.utils import timezone

from country_workspace.context import batch_ctx
from country_workspace.models import AsyncJob, Household, Individual, Program
from country_workspace.state import state
from country_workspace.utils.imports import validate_alien_fields

logger = logging.getLogger(__name__)
UNIQUE_VALIDATION_ERROR = "Value must be unique within the programme."
ARCHIVED_UNIQUE_VALIDATION_ERROR = "Value must be unique and cannot match previously pushed records."


def _normalize_unique_value(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _append_unique_error(obj: Model, field_name: str, message: str) -> None:
    errors = dict(getattr(obj, "errors", {}) or {})
    current = errors.get(field_name) or []
    if not isinstance(current, list):
        current = [str(current)]
    if message in current:
        return
    current.append(message)
    errors[field_name] = current
    obj.errors = errors
    obj.last_checked = timezone.now()
    obj.save(update_fields=["errors", "last_checked"])


def _append_household_member_invalid_error(obj: Model) -> None:
    errors = dict(getattr(obj, "errors", {}) or {})
    details = errors.get("dct") or []
    if not isinstance(details, list):
        details = [str(details)]
    marker = "Some members did not validate"
    if marker in details:
        return
    details.append(marker)
    errors["dct"] = details
    obj.errors = errors
    obj.last_checked = timezone.now()
    obj.save(update_fields=["errors", "last_checked"])


class UniqueValidationState:
    def __init__(self, *, field_name: str, archived_values: set[str]) -> None:
        self.field_name = field_name
        self.archived_values = archived_values
        self.seen_by_value: dict[str, Model] = {}

    def validate(self, obj: Model) -> set[int]:
        invalid_pks: set[int] = set()
        flex_fields = getattr(obj, "flex_fields", {}) or {}
        value = _normalize_unique_value(flex_fields.get(self.field_name))
        if not value:
            return invalid_pks

        if value in self.archived_values:
            _append_unique_error(obj, self.field_name, ARCHIVED_UNIQUE_VALIDATION_ERROR)
            invalid_pks.add(obj.pk)
            return invalid_pks

        if previous := self.seen_by_value.get(value):
            _append_unique_error(previous, self.field_name, UNIQUE_VALIDATION_ERROR)
            _append_unique_error(obj, self.field_name, UNIQUE_VALIDATION_ERROR)
            invalid_pks.add(previous.pk)
            invalid_pks.add(obj.pk)
            return invalid_pks

        self.seen_by_value[value] = obj
        return invalid_pks


def _build_unique_state(program: Program, model: type[Model]) -> UniqueValidationState | None:
    if not (field_name := program.get_unique_field_for(model)):
        return None
    archived_values = {value for value in program.get_removed_unique_values_for(model) if value}
    return UniqueValidationState(field_name=field_name, archived_values=archived_values)


def validate_queryset(queryset: QuerySet[Model], chunk_size: int = 2000, **kwargs: Any) -> dict[str, int]:
    valid = invalid = 0

    try:
        # Incluse forward FKs needed by the checker (no N+1 on program/country_office).
        queryset = queryset.select_related("batch__program", "batch__program__country_office")
        first = queryset.first()
        if not first:
            return {"valid": valid, "invalid": invalid}

        with state.set(tenant=first.country_office, program=first.program):
            unique_state = _build_unique_state(first.program, queryset.model)
            if issubclass(queryset.model, Household):
                individual_unique_state = _build_unique_state(first.program, Individual)
                # Reverse-FK prefetch for Household.members; include forward FKs for Individuals
                prefetch_members = Prefetch(
                    "members",
                    queryset=Individual.objects.select_related("batch__program", "batch__program__country_office"),
                )
                # Stream DB rows in a stable PK order
                it = queryset.order_by("pk").iterator(chunk_size=chunk_size)
                # Batch objects to prefetch their reverse relations once per batch.
                for chunk in batched(it, chunk_size):
                    # Populate members for all objects in this batch (no N+1 on members access).
                    prefetch_related_objects(chunk, prefetch_members)
                    dv, di = _validate_and_count(
                        chunk, unique_state=unique_state, member_unique_state=individual_unique_state
                    )
                    valid, invalid = valid + dv, invalid + di
            else:  # Individual
                # Just stream.
                dv, di = _validate_and_count(
                    queryset.iterator(chunk_size=chunk_size), unique_state=unique_state
                )  # stream rows from DB
                valid, invalid = valid + dv, invalid + di

    except Exception as e:  # pragma: no cover
        logger.error("Error during queryset validation: %s", e)
        raise

    return {"valid": valid, "invalid": invalid}


def _validate_and_count(
    objs: Iterable[Model],
    unique_state: UniqueValidationState | None = None,
    member_unique_state: UniqueValidationState | None = None,
) -> tuple[int, int]:
    total = 0
    invalid_pks: set[int] = set()
    aliens_checked = False

    for obj in objs:
        total += 1
        if not aliens_checked:
            validate_alien_fields(obj)
            aliens_checked = True

        with batch_ctx(obj.batch_id):
            if not obj.validate_with_checker():
                invalid_pks.add(obj.pk)
            if unique_state:
                invalid_pks |= unique_state.validate(obj)
            if member_unique_state and isinstance(obj, Household):
                member_invalid = False
                for member in obj.members.all():
                    if member_unique_state.validate(member):
                        member_invalid = True
                if member_invalid:
                    invalid_pks.add(obj.pk)
                    _append_household_member_invalid_error(obj)

    invalid = len(invalid_pks)
    valid = total - invalid
    return valid, invalid


def create_validation_jobs(description: str, owner: str, program: Program, queryset: QuerySet) -> AsyncJob:
    opts = queryset.model._meta
    queryset = queryset.order_by("pk").values_list("pk", flat=True)
    for chunk in batched(queryset, config.CHUNK_SIZE_FOR_VALIDATION_TASK):
        job = AsyncJob.objects.create(
            description=f"{description} (PKs {chunk[0]} - {chunk[-1]})",
            type=AsyncJob.JobType.ACTION,
            owner=owner,
            action=fqn(validate_queryset),
            program=program,
            config={"pks": chunk, "model_name": opts.label},
        )
        job.queue()
