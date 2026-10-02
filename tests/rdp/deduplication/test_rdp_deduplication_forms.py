import pytest

from country_workspace.rdp.deduplication.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.deduplication.types import ThresholdType


@pytest.mark.parametrize(
    ("threshold_type", "value", "valid"),
    [
        (ThresholdType.COUNT, "0", True),
        (ThresholdType.COUNT, "2", True),
        (ThresholdType.COUNT, "1.5", False),
        (ThresholdType.RATE, "1.5", True),
        (ThresholdType.RATE, "150", True),
    ],
)
def test_biometric_deduplication_config_form(
    threshold_type: ThresholdType,
    value: str,
    valid: bool,
) -> None:
    form = BiometricDeduplicationConfigForm(
        {
            "threshold_type": threshold_type,
            "threshold_value": value,
        },
        total_count=1,
    )

    assert form.is_valid() is valid
    if not valid:
        assert "threshold_value" in form.errors
