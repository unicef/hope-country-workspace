import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from django import forms
from django.core.serializers.json import DjangoJSONEncoder

from country_workspace.models import Program, RdpOperation

from .deduplication.forms import BiometricDeduplicationConfigForm
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
