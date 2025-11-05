import pytest
from django import forms

from country_workspace.contrib.hope.required_choice_field import (
    RequiredChoiceFieldWithEmptyDisplay,
    SelectWithEmptyOption,
)


def test_widget_adds_empty_option():
    widget = SelectWithEmptyOption(choices=[("male", "Male"), ("female", "Female")])

    groups = widget.optgroups(name="sex", value="", attrs=None)

    empty_option = groups[0][1][0]
    assert empty_option["value"] == ""
    assert empty_option["label"] == "None"

    all_options = [opt for _, group_choices, _ in groups for opt in group_choices]
    assert len(all_options) == 3


def test_widget_custom_empty_label():
    widget = SelectWithEmptyOption(choices=[("male", "Male"), ("female", "Female")], empty_label="Please select")

    groups = widget.optgroups(name="sex", value="", attrs=None)

    empty_option = groups[0][1][0]
    assert empty_option["label"] == "Please select"


def test_widget_does_not_duplicate_empty():
    widget = SelectWithEmptyOption(choices=[("", "Already empty"), ("male", "Male")])

    groups = widget.optgroups(name="sex", value="", attrs=None)

    empty_count = sum(1 for _, group_choices, _ in groups for opt in group_choices if opt["value"] in ("", None))

    assert empty_count == 1


def test_widget_renders_html_with_empty():
    widget = SelectWithEmptyOption(choices=[("male", "Male"), ("female", "Female")])

    html = widget.render(name="sex", value="")

    assert '<option value="">None</option>' in html
    assert '<option value="male">Male</option>' in html


def test_field_validates_empty_as_invalid():
    field = RequiredChoiceFieldWithEmptyDisplay(choices=[("male", "Male"), ("female", "Female")], required=True)

    with pytest.raises(forms.ValidationError):
        field.clean("")


def test_field_accepts_valid_choice():
    field = RequiredChoiceFieldWithEmptyDisplay(choices=[("male", "Male"), ("female", "Female")], required=True)

    result = field.clean("male")
    assert result == "male"


def test_field_rejects_invalid_choice():
    field = RequiredChoiceFieldWithEmptyDisplay(choices=[("male", "Male"), ("female", "Female")], required=True)

    with pytest.raises(forms.ValidationError):
        field.clean("invalid")


def test_field_works_in_form():
    class TestForm(forms.Form):
        sex = RequiredChoiceFieldWithEmptyDisplay(choices=[("male", "Male"), ("female", "Female")], required=True)

    form_empty = TestForm(data={"sex": ""})
    assert not form_empty.is_valid()

    form_valid = TestForm(data={"sex": "male"})
    assert form_valid.is_valid()
    assert form_valid.cleaned_data["sex"] == "male"

    form = TestForm()
    html = str(form["sex"])
    assert '<option value="">None</option>' in html
