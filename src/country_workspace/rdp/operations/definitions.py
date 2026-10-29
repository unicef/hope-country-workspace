import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from django import forms
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from country_workspace.models import Program, RdpOperation
from country_workspace.rdp.deduplication.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.deduplication.types import BiometricFindingType
from country_workspace.rdp.deduplication.workflow import run_biometric_deduplication
from country_workspace.rdp.ocr.forms import OcrConfigForm
from country_workspace.rdp.ocr.types import OcrFindingType
from country_workspace.rdp.ocr.workflow import run_ocr
from country_workspace.rdp.types import CreateRdpOperationConfig, JSONValue


@dataclass(frozen=True, slots=True)
class RdpOperationDefinition:
    operation_type: RdpOperation.Type
    config_form: type[forms.Form]
    finding_types: type[TextChoices]
    is_enabled: Callable[[Program], bool]
    runner: Callable[[RdpOperation], None]
    operation_id_label: str = _("Operation ID")
    can_retry_while_running: bool = False


RDP_OPERATION_DEFINITIONS: dict[str, RdpOperationDefinition] = {
    RdpOperation.Type.BIOMETRIC_DEDUPLICATION: RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        config_form=BiometricDeduplicationConfigForm,
        finding_types=BiometricFindingType,
        is_enabled=lambda program: program.biometric_deduplication_enabled,
        runner=run_biometric_deduplication,
        operation_id_label=_("Deduplication set ID"),
    ),
    RdpOperation.Type.OCR: RdpOperationDefinition(
        operation_type=RdpOperation.Type.OCR,
        config_form=OcrConfigForm,
        finding_types=OcrFindingType,
        is_enabled=lambda __: True,
        runner=run_ocr,
        can_retry_while_running=True,
    ),
}


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
