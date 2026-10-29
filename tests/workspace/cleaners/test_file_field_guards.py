from typing import Any

import pytest
from hope_flex_fields.models import DataChecker

from country_workspace.models import Office
from country_workspace.workspaces.admin.cleaners.concatenate import ConcatenateFieldForm
from country_workspace.workspaces.admin.cleaners.mass_update import MassUpdateForm
from country_workspace.workspaces.admin.cleaners.name_parser import NameParserForm
from country_workspace.workspaces.admin.cleaners.regex import RegexUpdateForm

pytestmark = pytest.mark.django_db


def test_mass_update_has_no_field_for_an_image(photo_checker: DataChecker) -> None:
    form = MassUpdateForm(checker=photo_checker)

    assert "flex_fields__family_name" in form.fields
    assert "flex_fields__photo" not in form.fields


@pytest.mark.parametrize(
    ("form_class", "field_name"),
    [
        pytest.param(RegexUpdateForm, "field", id="regex"),
        pytest.param(ConcatenateFieldForm, "destination_field", id="concatenate"),
        pytest.param(NameParserForm, "source_field", id="name-parser"),
    ],
)
def test_cleaner_choices_leave_out_image_fields(
    photo_checker: DataChecker, afghanistan: Office, form_class: type, field_name: str
) -> None:
    extra: dict[str, Any] = {"tenant": afghanistan} if form_class is NameParserForm else {}

    form = form_class(checker=photo_checker, **extra)

    values = [value for value, _label in form.fields[field_name].choices]
    assert "family_name" in values
    assert "photo" not in values
