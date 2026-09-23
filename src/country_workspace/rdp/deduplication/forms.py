from decimal import Decimal

from django import forms

from .types import ThresholdType


class BiometricDeduplicationConfigForm(forms.Form):
    threshold_type = forms.ChoiceField(
        choices=(
            (ThresholdType.COUNT, "Number of duplicate individuals"),
            (ThresholdType.PERCENT, "Percentage of RDP individuals"),
        ),
        initial=ThresholdType.COUNT,
        widget=forms.RadioSelect,
    )
    threshold_value = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, initial=0)

    def clean(self) -> dict[str, object]:
        """Validate the biometric deduplication threshold."""
        cleaned = super().clean()
        threshold_type = cleaned.get("threshold_type")
        value = cleaned.get("threshold_value")

        if not isinstance(value, Decimal):
            return cleaned

        if threshold_type == ThresholdType.COUNT and value != value.to_integral_value():
            self.add_error("threshold_value", "The number of individuals must be a whole number.")
        elif threshold_type == ThresholdType.PERCENT and value > 100:
            self.add_error("threshold_value", "Percentage cannot exceed 100.")

        return cleaned
