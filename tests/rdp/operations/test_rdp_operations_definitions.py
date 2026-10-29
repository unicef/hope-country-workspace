from decimal import Decimal

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.ocr.forms import OcrConfigForm
from country_workspace.rdp.operations.definitions import (
    RDP_OPERATION_DEFINITIONS,
    get_enabled_rdp_operation_definitions,
    get_rdp_operation_forms,
    get_validated_rdp_operation_configs,
)


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [
        (True, (RdpOperation.Type.BIOMETRIC_DEDUPLICATION, RdpOperation.Type.OCR)),
        (False, (RdpOperation.Type.OCR,)),
    ],
)
def test_get_enabled_rdp_operation_definitions(
    program,
    enabled: bool,
    expected: tuple[RdpOperation.Type, ...],
) -> None:
    program.biometric_deduplication_enabled = enabled

    definitions = get_enabled_rdp_operation_definitions(program)

    assert tuple(definition.operation_type for definition in definitions) == expected


def test_get_rdp_operation_forms(program) -> None:
    program.biometric_deduplication_enabled = True

    forms = get_rdp_operation_forms(program=program)

    assert [definition.operation_type for definition, _ in forms] == [
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
        RdpOperation.Type.OCR,
    ]
    assert isinstance(forms[0][1], BiometricDeduplicationConfigForm)
    assert isinstance(forms[1][1], OcrConfigForm)
    assert [form.prefix for _, form in forms] == [
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION.value.lower(),
        RdpOperation.Type.OCR.value.lower(),
    ]


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
