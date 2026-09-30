from decimal import Decimal

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.operations.definitions import (
    RDP_OPERATION_DEFINITIONS,
    get_enabled_rdp_operation_definitions,
    get_rdp_operation_forms,
    get_validated_rdp_operation_configs,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("enabled", [True, False])
def test_get_enabled_rdp_operation_definitions(program, enabled: bool) -> None:
    program.biometric_deduplication_enabled = enabled

    definitions = get_enabled_rdp_operation_definitions(program)

    assert definitions == ((RDP_OPERATION_DEFINITIONS[RdpOperation.Type.BIOMETRIC_DEDUPLICATION],) if enabled else ())


def test_get_rdp_operation_forms(program) -> None:
    program.biometric_deduplication_enabled = True

    [(definition, form)] = get_rdp_operation_forms(program=program, total_count=42)

    assert definition.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    assert isinstance(form, BiometricDeduplicationConfigForm)
    assert form.prefix == RdpOperation.Type.BIOMETRIC_DEDUPLICATION.value.lower()
    assert form.total_count == 42


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


def test_get_validated_rdp_operation_configs_returns_none_for_invalid_forms(
    mocker: MockerFixture,
) -> None:
    definition = RDP_OPERATION_DEFINITIONS[RdpOperation.Type.BIOMETRIC_DEDUPLICATION]
    invalid = mocker.MagicMock()
    invalid.is_valid.return_value = False
    valid = mocker.MagicMock()
    valid.is_valid.return_value = True

    assert get_validated_rdp_operation_configs([(definition, invalid), (definition, valid)]) is None

    invalid.is_valid.assert_called_once_with()
    valid.is_valid.assert_called_once_with()
