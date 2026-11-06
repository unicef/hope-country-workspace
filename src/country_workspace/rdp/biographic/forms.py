from django import forms

from country_workspace.rdp.deduplication.forms import BiometricDeduplicationConfigForm
from country_workspace.rdp.deduplication.types import ThresholdType


class BiographicDeduplicationConfigForm(BiometricDeduplicationConfigForm):
    """Threshold of individuals with biographic duplicates before an RDP requires manual review."""

    threshold_type = forms.ChoiceField(
        choices=(
            (ThresholdType.COUNT, "Number of individuals with duplicates"),
            (ThresholdType.RATE, "Individuals with duplicates per 100 RDP individuals"),
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
            "Defines how many individuals may have biographic duplicates before the RDP requires manual review. "
            "The rate is measured as individuals with duplicates per 100 RDP individuals."
        ),
    )
