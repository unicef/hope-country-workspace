import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, cast

from django import forms
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from country_workspace.models import Program, RdpOperation
from country_workspace.rdp.deduplication.biographic.forms import BiographicDeduplicationConfigForm
from country_workspace.rdp.deduplication.biographic.types import BiographicFindingType
from country_workspace.rdp.deduplication.biographic.workflow import run_biographic_deduplication
from country_workspace.rdp.deduplication.biometric.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.deduplication.biometric.types import BiometricFindingType
from country_workspace.rdp.deduplication.biometric.workflow import run_biometric_deduplication
from country_workspace.rdp.ocr.forms import OcrConfigForm
from country_workspace.rdp.ocr.types import OcrFindingType
from country_workspace.rdp.ocr.workflow import run_ocr
from country_workspace.rdp.types import CreateRdpOperationConfig, JSONValue


@dataclass(frozen=True, slots=True)
class RdpOperationDefinition:
    operation_type: RdpOperation.Type
    short_label: str
    config_form: type[forms.Form]
    finding_types: type[TextChoices]
    is_enabled: Callable[[Program], bool]
    runner: Callable[[RdpOperation], None]
    operation_id_label: str = _("Operation ID")
    can_retry_while_running: bool = False
    is_cw_managed: bool = True


RDP_OPERATION_DEFINITIONS: dict[str, RdpOperationDefinition] = {
    RdpOperation.Type.BIOMETRIC_DEDUPLICATION: RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        short_label=_("Biometric"),
        config_form=BiometricDeduplicationConfigForm,
        finding_types=BiometricFindingType,
        is_enabled=lambda program: program.biometric_deduplication_enabled,
        runner=run_biometric_deduplication,
        operation_id_label=_("Deduplication set ID"),
        is_cw_managed=False,
    ),
    RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION: RdpOperationDefinition(
        operation_type=RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
        short_label=_("Biographic"),
        config_form=BiographicDeduplicationConfigForm,
        finding_types=BiographicFindingType,
        is_enabled=lambda __: True,
        runner=run_biographic_deduplication,
        operation_id_label=_("Dataset ID"),
    ),
    RdpOperation.Type.OCR: RdpOperationDefinition(
        operation_type=RdpOperation.Type.OCR,
        short_label=_("OCR"),
        config_form=OcrConfigForm,
        finding_types=OcrFindingType,
        is_enabled=lambda __: True,
        runner=run_ocr,
        can_retry_while_running=True,
    ),
}


def get_enabled_rdp_operation_definitions(program: Program) -> tuple[RdpOperationDefinition, ...]:
    """Return operation definitions enabled for the program."""
    configured = program.enabled_rdp_operations
    return tuple(
        definition
        for definition in RDP_OPERATION_DEFINITIONS.values()
        if (
            definition.operation_type.value in configured
            if definition.is_cw_managed and configured is not None
            else definition.is_enabled(program)
        )
    )


def get_rdp_operation_forms(
    *,
    program: Program,
    data: Any = None,
    selected_operations: Collection[str] | None = None,
) -> list[tuple[RdpOperationDefinition, forms.Form]]:
    """Build operation forms, binding only selected and non-CW-managed operations."""
    operation_forms = []

    for definition in get_enabled_rdp_operation_definitions(program):
        selected = (
            selected_operations is None
            or not definition.is_cw_managed
            or definition.operation_type.value in selected_operations
        )
        operation_forms.append(
            (
                definition,
                definition.config_form(data if selected else None, prefix=definition.operation_type.value.lower()),
            )
        )

    return operation_forms


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
