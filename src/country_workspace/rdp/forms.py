from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django import forms
from django.http import QueryDict
from django.utils.translation import gettext_lazy as _

from country_workspace.models import Household, Individual, RdpOperation

from .types import OperationLogResult, ThresholdType


class ThresholdConfigForm(forms.Form):
    """Configure an RDP operation review threshold."""

    rate_help_text = ""

    threshold_type = forms.ChoiceField(
        label="Threshold type",
        initial=ThresholdType.COUNT,
        widget=forms.RadioSelect,
    )
    threshold_value = forms.DecimalField(
        label="Threshold",
        min_value=0,
        max_digits=12,
        decimal_places=2,
        initial=0,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["threshold_type"].choices = (
            (ThresholdType.COUNT, "Number of findings"),
            (ThresholdType.RATE, "Findings rate"),
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


class RdpFindingsFilterForm(forms.Form):
    finding_type = forms.ChoiceField(label=_("Finding type"), required=False)
    individual_id = forms.IntegerField(
        label=_("Individual ID"),
        required=False,
        min_value=1,
        validators=Individual._meta.pk.validators,
        help_text=_("Also matches related individuals."),
    )
    household_id = forms.IntegerField(
        label=_("Household ID"),
        required=False,
        min_value=1,
        validators=Household._meta.pk.validators,
        help_text=_("Also matches households of related individuals."),
    )

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        finding_types: list[tuple[str, str]],
        include_household: bool = True,
    ) -> None:
        super().__init__(data=data)
        cast("forms.ChoiceField", self.fields["finding_type"]).choices = [("", _("All types")), *finding_types]
        if not include_household:
            self.fields.pop("household_id")


class CleanRdpForm(forms.Form):
    clean_operations = forms.TypedMultipleChoiceField(
        coerce=UUID,
        label=_("Clean findings from"),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        help_text=_(
            "Checked operations will exclude beneficiaries affected by their findings. "
            "Unchecked operations approve their remaining findings. "
            "At least one operation must be checked."
        ),
    )

    def __init__(
        self,
        *args: Any,
        operations: list[tuple[RdpOperation, OperationLogResult]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        field = cast("forms.TypedMultipleChoiceField", self.fields["clean_operations"])
        field.choices = choices = [
            (
                str(operation.pk),
                f"{operation.get_operation_type_display()}: {result['findings_count']} findings",
            )
            for operation, result in operations
        ]
        if not self.is_bound:
            self.initial["clean_operations"] = [value for value, __ in choices]
