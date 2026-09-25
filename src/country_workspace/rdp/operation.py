import json
from dataclasses import dataclass
from typing import Any, cast, TYPE_CHECKING
from uuid import UUID
from strategy_field.utils import fqn

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from country_workspace.models import AsyncJob, Program, Rdp, RdpOperation, RdpOperationFinding

from .deduplication.forms import BiometricDeduplicationConfigForm
from .repository import lock_rdp_for_update, lock_rdp_operation_for_update

if TYPE_CHECKING:
    from collections.abc import Callable
    from django import forms
    from .types import CreateRdpOperationConfig, JSONValue


@dataclass(frozen=True, slots=True)
class RdpOperationDefinition:
    operation_type: RdpOperation.Type
    config_form: type[forms.Form]
    config_form_kwargs: Callable[[Program, int], dict[str, Any]]
    is_enabled: Callable[[Program], bool]


RDP_OPERATION_DEFINITIONS = (
    RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        config_form=BiometricDeduplicationConfigForm,
        config_form_kwargs=lambda _program, total_count: {"total_count": total_count},
        is_enabled=lambda program: program.biometric_deduplication_enabled,
    ),
)


def get_enabled_rdp_operation_definitions(program: Program) -> tuple[RdpOperationDefinition, ...]:
    """Return operation definitions enabled for the program."""
    return tuple(definition for definition in RDP_OPERATION_DEFINITIONS if definition.is_enabled(program))


def get_rdp_operation_forms(
    *,
    program: Program,
    total_count: int,
    data: Any = None,
) -> list[tuple[RdpOperationDefinition, forms.Form]]:
    """Build enabled operation configuration forms."""
    return [
        (
            definition,
            definition.config_form(
                data,
                prefix=definition.operation_type.value.lower(),
                **definition.config_form_kwargs(program, total_count),
            ),
        )
        for definition in get_enabled_rdp_operation_definitions(program)
    ]


def get_validated_rdp_operation_configs(
    operation_forms: list[tuple[RdpOperationDefinition, forms.Form]],
) -> list[CreateRdpOperationConfig] | None:
    """Validate operation forms and return their JSON-safe configs."""
    results = [form.is_valid() for _, form in operation_forms]
    if not all(results):
        return None

    return [
        {
            "operation_type": definition.operation_type.value,
            "config": cast(
                "dict[str, JSONValue]",
                json.loads(json.dumps(form.cleaned_data, cls=DjangoJSONEncoder)),
            ),
        }
        for definition, form in operation_forms
    ]


def claim_rdp_operation(operation_id: UUID) -> RdpOperation | None:
    """Claim a pending or failed RDP operation for execution."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        rdp = lock_rdp_for_update(pk=operation.rdp_id)

        if rdp.status != Rdp.PushStatus.PENDING or operation.status not in {
            RdpOperation.Status.PENDING,
            RdpOperation.Status.FAILURE,
        }:
            return None

        operation.status = RdpOperation.Status.RUNNING
        operation.attempt += 1
        operation.error = {}
        operation.started_at = timezone.now()
        operation.finished_at = None
        operation.save(update_fields=["status", "attempt", "error", "started_at", "finished_at"])

    return operation


def fail_rdp_operation(*, operation_id: UUID, error: dict[str, JSONValue]) -> bool:
    """Mark a running RDP operation as failed."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        if operation.status != RdpOperation.Status.RUNNING:
            return False

        operation.status = RdpOperation.Status.FAILURE
        operation.error = error
        operation.finished_at = timezone.now()
        operation.save(update_fields=["status", "error", "finished_at"])

    return True


def finish_rdp_operation(*, operation_id: UUID, findings: list[RdpOperationFinding]) -> bool:
    """Replace findings and mark a running RDP operation as successful."""
    with transaction.atomic():
        operation = lock_rdp_operation_for_update(pk=operation_id)
        if operation.status != RdpOperation.Status.RUNNING:
            return False

        operation.findings.all().delete()
        for finding in findings:
            finding.operation = operation
        RdpOperationFinding.objects.bulk_create(findings)

        operation.status = RdpOperation.Status.SUCCESS
        operation.error = {}
        operation.finished_at = timezone.now()
        operation.save(update_fields=["status", "error", "finished_at"])

    return True


def schedule_rdp_operation(*, operation: RdpOperation, owner_id: int) -> AsyncJob:
    """Create and queue an RDP operation job after commit."""
    job = AsyncJob.objects.create(
        description=f"Run RDP operation: {RdpOperation.Type(operation.operation_type).label}",
        type=AsyncJob.JobType.TASK,
        owner_id=owner_id,
        action=fqn(run_rdp_operation_core),
        program_id=operation.rdp.program_id,
        rdp_id=operation.rdp_id,
        config={"operation_id": str(operation.id)},
    )
    transaction.on_commit(job.queue)
    return job


def run_rdp_operation_core(job: AsyncJob) -> dict[str, JSONValue]:
    """Run the RDP operation referenced by an async job."""
    operation_id = UUID(job.config["operation_id"])
    if (operation := claim_rdp_operation(operation_id)) is None:
        return {"operation_id": str(operation_id), "started": False}

    if operation.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
        from .deduplication.workflow import run_biometric_deduplication

        run_biometric_deduplication(operation)
    else:
        message = f"Unsupported RDP operation type: {operation.operation_type!r}"
        fail_rdp_operation(operation_id=operation.id, error={"message": message})
        raise ValueError(message)

    return {"operation_id": str(operation.id), "started": True}
