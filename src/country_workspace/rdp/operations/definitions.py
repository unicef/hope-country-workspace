import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from django import forms
from django.core.serializers.json import DjangoJSONEncoder

from country_workspace.models import Program, RdpOperation
from country_workspace.rdp.biographic.forms import BiographicDeduplicationConfigForm
from country_workspace.rdp.biographic.workflow import (
    run_biographic_deduplication,
    sync_biographic_deduplication_result,
)
from country_workspace.rdp.deduplication.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.deduplication.workflow import (
    run_biometric_deduplication,
    sync_biometric_deduplication_result,
)
from country_workspace.rdp.types import CreateRdpOperationConfig, JSONValue


@dataclass(frozen=True, slots=True)
class RdpOperationDefinition:
    operation_type: RdpOperation.Type
    config_form: type[forms.Form]
    is_enabled: Callable[[Program], bool]
    runner: Callable[[RdpOperation], None]
    sync_result: Callable[..., bool]


RDP_OPERATION_DEFINITIONS: dict[RdpOperation.Type, RdpOperationDefinition] = {
    RdpOperation.Type.BIOMETRIC_DEDUPLICATION: RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        config_form=BiometricDeduplicationConfigForm,
        is_enabled=lambda program: program.biometric_deduplication_enabled,
        runner=run_biometric_deduplication,
        sync_result=sync_biometric_deduplication_result,
    ),
    RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION: RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
        config_form=BiographicDeduplicationConfigForm,
        is_enabled=lambda program: program.biographic_deduplication_enabled,
        runner=run_biographic_deduplication,
        sync_result=sync_biographic_deduplication_result,
    ),
}


def sync_rdp_operation_result(*, operation_id: UUID) -> bool:
    """Synchronize an RDP operation with the external system that runs it."""
    operation_type = RdpOperation.objects.filter(pk=operation_id).values_list("operation_type", flat=True).first()
    if (definition := RDP_OPERATION_DEFINITIONS.get(operation_type)) is None:
        return False
    return definition.sync_result(operation_id=operation_id)


def get_enabled_rdp_operation_definitions(program: Program) -> tuple[RdpOperationDefinition, ...]:
    """Return operation definitions enabled for the program."""
    return tuple(definition for definition in RDP_OPERATION_DEFINITIONS.values() if definition.is_enabled(program))


def get_rdp_operation_forms(
    *,
    program: Program,
    data: Any = None,
) -> list[tuple[RdpOperationDefinition, forms.Form]]:
    """Build enabled operation configuration forms."""
    return [
        (
            definition,
            definition.config_form(data, prefix=definition.operation_type.value.lower()),
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
