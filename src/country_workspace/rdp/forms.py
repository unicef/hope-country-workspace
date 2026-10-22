from decimal import Decimal
from typing import Any

from django import forms

from .types import ThresholdType


class ThresholdConfigForm(forms.Form):
    """Configure an RDP operation review threshold."""

    rate_label = "Findings per 100 records"

    threshold_type = forms.ChoiceField(initial=ThresholdType.COUNT, widget=forms.RadioSelect)
    threshold_value = forms.DecimalField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        initial=0,
        help_text="Defines the findings threshold before the RDP requires manual review.",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["threshold_type"].choices = (
            (ThresholdType.COUNT, "Number of findings"),
            (ThresholdType.RATE, self.rate_label),
        )

    def clean(self) -> dict[str, object]:
        """Validate the review threshold."""
        cleaned = super().clean()
        if (
            cleaned.get("threshold_type") == ThresholdType.COUNT
            and isinstance(value := cleaned.get("threshold_value"), Decimal)
            and value != value.to_integral_value()
        ):
            self.add_error("threshold_value", "The number of findings must be a whole number.")
        return cleaned
