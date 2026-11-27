from typing import Final

from django import forms
from hope_flex_fields.fields import IdentityField
from hope_flex_fields.models import DataChecker

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.utils.flex_fields import get_checker_field_types

from .collector_linkage import REFERENCE_FIELDS
from .structural_fields import STRUCTURAL_FIELDS


_PROTECTED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "household_id",
        *REFERENCE_FIELDS,
        *HOUSEHOLD_ROLE_REF_FIELDS,
        *STRUCTURAL_FIELDS,
        "head_of_household",
        "primary_collector",
        "alternate_collector",
    }
)


def get_normalizable_field_types(checker: DataChecker | None) -> dict[str, type[forms.Field]]:
    """Return field types eligible for import normalization."""
    return {
        name: field_type
        for name, field_type in get_checker_field_types(checker).items()
        if name not in _PROTECTED_FIELDS and not issubclass(field_type, IdentityField)
    }
