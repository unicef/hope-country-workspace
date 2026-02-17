from typing import TYPE_CHECKING, Any

from django import forms
from django.db import transaction

from country_workspace.contrib.name_parser.parser import NAME_TYPES, get_parser
from country_workspace.utils.flex_fields import get_checker_fields

from .base import BaseActionForm

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from hope_flex_fields.models import DataChecker

    from country_workspace.models import Office
    from country_workspace.types import Beneficiary


class NameParserForm(BaseActionForm):
    """
    Form for parsing full names into separate components (given name, middle name, family name).

    This action uses machine learning models to intelligently split full names into their
    constituent parts, helping to standardize name data that was collected in a single field.
    This is particularly useful for:
    - Data standardization across different sources
    - Proper name formatting for official documents
    - Improved searchability and filtering by name components
    - Compliance with systems that require separate name fields
    """

    source_field = forms.ChoiceField(choices=[])
    country_code = forms.ChoiceField(label="Country for parsing model", choices=[])
    given_name_field = forms.ChoiceField(choices=[], required=False)
    middle_name_field = forms.ChoiceField(choices=[], required=False)
    family_name_field = forms.ChoiceField(choices=[], required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        checker: "DataChecker" = kwargs.pop("checker")
        tenant: "Office" = kwargs.pop("tenant")
        super().__init__(*args, **kwargs)
        choices = [("", "---")] + list(get_checker_fields(checker, with_fs_prefix=True))
        self.fields["source_field"].choices = choices
        self.fields["given_name_field"].choices = choices
        self.fields["middle_name_field"].choices = choices
        self.fields["family_name_field"].choices = choices

        country_choices = [(c.iso_code3.upper(), c.name) for c in tenant.countries.all()]
        self.fields["country_code"].choices = country_choices
        if len(country_choices) == 1:
            self.fields["country_code"].initial = country_choices[0][0]

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()

        if not any(
            [
                cleaned_data.get("given_name_field"),
                cleaned_data.get("middle_name_field"),
                cleaned_data.get("family_name_field"),
            ]
        ):
            raise forms.ValidationError("At least one destination field must be selected.")

        source_field = cleaned_data.get("source_field")
        destination_fields = [
            cleaned_data.get("given_name_field"),
            cleaned_data.get("middle_name_field"),
            cleaned_data.get("family_name_field"),
        ]

        for field in destination_fields:
            if field and field == source_field:
                raise forms.ValidationError(
                    f"The source field cannot be the same as a destination field. "
                    f"'{source_field}' is selected as both source and destination."
                )

        selected_destinations = [f for f in destination_fields if f]
        if len(selected_destinations) != len(set(selected_destinations)):
            raise forms.ValidationError(
                "Each destination field must be unique. You cannot use the same field for multiple name parts."
            )

        return cleaned_data


def name_parser_impl(
    records: "QuerySet[Beneficiary]",
    config: dict[str, Any],
    save: bool = True,
) -> None:
    source_field = config["source_field"]
    field_mapping = {
        "given_name": config.get("given_name_field"),
        "middle_name": config.get("middle_name_field"),
        "family_name": config.get("family_name_field"),
    }
    # Filter out empty fields
    field_mapping = {k: v for k, v in field_mapping.items() if v}

    parser = get_parser(config["country_code"])

    with transaction.atomic():
        for record in records:
            full_name = record.flex_fields.get(source_field)
            if not isinstance(full_name, str):
                continue

            name_parts = full_name.split()
            if not name_parts:
                continue

            parsed_types = parser(full_name)

            # Group parts by type
            grouped_parts: dict[str, list[str]] = {name_type: [] for name_type in NAME_TYPES}
            for part, name_type in zip(name_parts, parsed_types, strict=False):
                grouped_parts[name_type].append(part)

            for name_type, field_name in field_mapping.items():
                parts = grouped_parts[name_type]
                if parts:  # Only set the field if there are parts to join
                    record.flex_fields[field_name] = " ".join(parts)

        if save:
            records.bulk_update(records, ["flex_fields"], batch_size=1000)
