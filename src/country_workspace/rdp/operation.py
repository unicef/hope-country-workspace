from collections.abc import Callable
from dataclasses import dataclass

from django import forms

from country_workspace.models import Program, RdpOperation

from .deduplication.forms import BiometricDeduplicationConfigForm


@dataclass(frozen=True, slots=True)
class RdpOperationDefinition:
    operation_type: RdpOperation.Type
    config_form: type[forms.Form]
    is_enabled: Callable[[Program], bool]


RDP_OPERATION_DEFINITIONS = (
    RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        config_form=BiometricDeduplicationConfigForm,
        is_enabled=lambda program: program.biometric_deduplication_enabled,
    ),
)


def get_enabled_rdp_operation_definitions(program: Program) -> tuple[RdpOperationDefinition, ...]:
    """Return operation definitions enabled for the program."""
    return tuple(definition for definition in RDP_OPERATION_DEFINITIONS if definition.is_enabled(program))
