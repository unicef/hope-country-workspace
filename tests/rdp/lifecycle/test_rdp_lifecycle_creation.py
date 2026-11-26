from decimal import Decimal

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Program, RdpOperation
from country_workspace.rdp.deduplication.biographic.forms import BiographicDeduplicationConfigForm
from country_workspace.rdp.deduplication.biometric.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.ocr.forms import OcrConfigForm
from country_workspace.rdp.operations.definitions import (
    RDP_OPERATION_DEFINITIONS,
    get_enabled_rdp_operation_definitions,
    get_rdp_operation_forms,
    get_validated_rdp_operation_configs,
)


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("enabled", [True, False], ids=["biometric-enabled", "biometric-disabled"])
@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, (RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.OCR)),
        ([], ()),
        ([RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION], (RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,)),
        ([RdpOperation.Type.OCR], (RdpOperation.Type.OCR,)),
        (
            [RdpOperation.Type.OCR, RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION],
            (RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.OCR),
        ),
    ],
    ids=["defaults", "empty", "biographic", "ocr", "both"],
)
def test_get_enabled_rdp_operation_definitions(
    program: Program,
    enabled: bool,
    configured: list[str] | None,
    expected: tuple[RdpOperation.Type, ...],
) -> None:
    program.biometric_deduplication_enabled = enabled
    program.enabled_rdp_operations = configured

    if enabled:
        expected = (RdpOperation.Type.BIOMETRIC_DEDUPLICATION, *expected)

    definitions = get_enabled_rdp_operation_definitions(program)

    assert tuple(definition.operation_type for definition in definitions) == expected


def test_biographic_operation_definition() -> None:
    definition = RDP_OPERATION_DEFINITIONS[RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION]

    assert definition.config_form is BiographicDeduplicationConfigForm
    assert definition.short_label == "Biographic"
    assert definition.operation_id_label == "Dataset ID"
    assert definition.can_retry_while_running is False


def test_get_rdp_operation_forms(program: Program) -> None:
    program.biometric_deduplication_enabled = True
    program.enabled_rdp_operations = None

    forms = get_rdp_operation_forms(program=program)

    assert [definition.operation_type for definition, _ in forms] == [
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
        RdpOperation.Type.OCR,
    ]
    assert all(not form.is_bound for _, form in forms)
    assert isinstance(forms[0][1], BiometricDeduplicationConfigForm)
    assert isinstance(forms[1][1], BiographicDeduplicationConfigForm)
    assert isinstance(forms[2][1], OcrConfigForm)
    assert [form.prefix for _, form in forms] == [
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION.value.lower(),
        RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION.value.lower(),
        RdpOperation.Type.OCR.value.lower(),
    ]


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (
            None,
            {
                RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
                RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
                RdpOperation.Type.OCR,
            },
        ),
        ([RdpOperation.Type.OCR], {RdpOperation.Type.BIOMETRIC_DEDUPLICATION, RdpOperation.Type.OCR}),
        ([], {RdpOperation.Type.BIOMETRIC_DEDUPLICATION}),
    ],
    ids=["all-by-default", "ocr-selected", "none-selected"],
)
def test_get_rdp_operation_forms_binds_only_selected_operations(
    program: Program,
    selected: list[str] | None,
    expected: set[RdpOperation.Type],
) -> None:
    program.biometric_deduplication_enabled = True
    program.enabled_rdp_operations = None

    forms = get_rdp_operation_forms(program=program, data={}, selected_operations=selected)

    assert len(forms) == 3
    assert {definition.operation_type for definition, form in forms if form.is_bound} == expected


def test_get_rdp_operation_forms_excludes_disabled_operations(program: Program) -> None:
    program.biometric_deduplication_enabled = False
    program.enabled_rdp_operations = [RdpOperation.Type.OCR]

    forms = get_rdp_operation_forms(
        program=program,
        data={},
        selected_operations=[RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.OCR],
    )

    assert [definition.operation_type for definition, _ in forms] == [RdpOperation.Type.OCR]
    assert forms[0][1].is_bound


def test_get_validated_rdp_operation_configs(mocker: MockerFixture) -> None:
    definition = RDP_OPERATION_DEFINITIONS[RdpOperation.Type.BIOMETRIC_DEDUPLICATION]
    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {
        "threshold_type": "count",
        "threshold_value": Decimal(2),
    }

    assert get_validated_rdp_operation_configs([(definition, form)]) == [
        {
            "operation_type": RdpOperation.Type.BIOMETRIC_DEDUPLICATION.value,
            "config": {
                "threshold_type": "count",
                "threshold_value": "2",
            },
        }
    ]


def test_get_validated_rdp_operation_configs_returns_none_for_invalid_form(
    mocker: MockerFixture,
) -> None:
    definition = RDP_OPERATION_DEFINITIONS[RdpOperation.Type.BIOMETRIC_DEDUPLICATION]
    form = mocker.MagicMock()
    form.is_valid.return_value = False

    assert get_validated_rdp_operation_configs([(definition, form)]) is None
