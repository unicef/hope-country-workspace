import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from django import forms
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Program, RdpOperation
from country_workspace.models.rdp import RdpPushStatus

from .deduplication.forms import BiometricDeduplicationConfigForm
from .deduplication.workflow import run_biometric_deduplication
from .repository import claim_rdp_operation, fail_rdp_operation, failed_rdp_operations, lock_rdp_for_update
from .types import CreateRdpOperationConfig, JSONValue


@dataclass(frozen=True, slots=True)
class RdpOperationDefinition:
    operation_type: RdpOperation.Type
    config_form: type[forms.Form]
    config_form_kwargs: Callable[[Program, int], dict[str, Any]]
    is_enabled: Callable[[Program], bool]
    runner: Callable[[RdpOperation], None]


RDP_OPERATION_DEFINITIONS: dict[str, RdpOperationDefinition] = {
    RdpOperation.Type.BIOMETRIC_DEDUPLICATION: RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        config_form=BiometricDeduplicationConfigForm,
        config_form_kwargs=lambda _program, total_count: {"total_count": total_count},
        is_enabled=lambda program: program.biometric_deduplication_enabled,
        runner=run_biometric_deduplication,
    ),
}


def get_enabled_rdp_operation_definitions(program: Program) -> tuple[RdpOperationDefinition, ...]:
    """Return operation definitions enabled for the program."""
    return tuple(definition for definition in RDP_OPERATION_DEFINITIONS.values() if definition.is_enabled(program))


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


def run_rdp_operation_core(job: AsyncJob) -> dict[str, JSONValue]:
    """Run the RDP operation referenced by an async job."""
    operation_id = UUID(job.config["operation_id"])
    if (operation := claim_rdp_operation(operation_id)) is None:
        return {"operation_id": str(operation_id), "started": False}

    if (definition := RDP_OPERATION_DEFINITIONS.get(operation.operation_type)) is None:
        message = f"Unsupported RDP operation type: {operation.operation_type!r}"
        fail_rdp_operation(operation_id=operation.id, error={"message": message})
        raise ValueError(message)

    try:
        definition.runner(operation)
    except Exception as exc:
        fail_rdp_operation(operation_id=operation.id, error={"message": str(exc)})
        raise

    return {"operation_id": str(operation.id), "started": True}


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
    transaction.on_commit(job.queue, robust=True)
    return job


def retry_failed_rdp_operations(*, rdp_id: int, owner_id: int) -> int:
    """Schedule failed operations of a pending RDP for retry."""
    with transaction.atomic():
        rdp = lock_rdp_for_update(pk=rdp_id)
        if rdp.status != RdpPushStatus.PENDING:
            return 0

        operations = list(failed_rdp_operations(rdp_id=rdp_id))
        for operation in operations:
            schedule_rdp_operation(operation=operation, owner_id=owner_id)

    return len(operations)
