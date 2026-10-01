from decimal import Decimal
from typing import Any

from django import forms

from .types import ThresholdType


class BiometricDeduplicationConfigForm(forms.Form):
    threshold_type = forms.ChoiceField(
        choices=(
            (ThresholdType.COUNT, "Number of findings"),
            (ThresholdType.RATE, "Findings per 100 RDP individuals"),
        ),
        initial=ThresholdType.COUNT,
        widget=forms.RadioSelect,
    )
    threshold_value = forms.DecimalField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        initial=0,
        help_text=(
            "Defines the biometric findings threshold before the RDP requires manual review. "
            "The rate is measured as findings per 100 RDP individuals."
        ),
    )

    def __init__(self, *args: Any, total_count: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.total_count = total_count

    def clean(self) -> dict[str, object]:
        """Validate the biometric deduplication threshold."""
        cleaned = super().clean()
        threshold_type = cleaned.get("threshold_type")
        value = cleaned.get("threshold_value")

        if threshold_type == ThresholdType.COUNT and isinstance(value, Decimal) and value != value.to_integral_value():
            self.add_error("threshold_value", "The number of findings must be a whole number.")

        return cleaned
