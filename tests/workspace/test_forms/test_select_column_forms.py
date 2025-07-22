from django import forms

from country_workspace.workspaces.admin.program import SelectColumnsForm, SelectIndividualColumnsForm
from tests.extras.testutils.factories.smart_fields import (
    DataCheckerFactory,
    DataCheckerFieldsetFactory,
    FieldDefinitionFactory,
    FieldsetFactory,
    FlexFieldFactory,
)


def test_init_with_checker_creates_choices_with_prefix():
    checker = DataCheckerFactory()
    fieldset1 = FieldsetFactory()
    fieldset2 = FieldsetFactory()

    char_field_def = FieldDefinitionFactory(field_type=forms.CharField)
    int_field_def = FieldDefinitionFactory(field_type=forms.IntegerField)

    FlexFieldFactory(fieldset=fieldset1, name="field1", definition=char_field_def, attrs={"label": "Field One"})
    FlexFieldFactory(fieldset=fieldset2, name="field2", definition=int_field_def, attrs={"label": "Field Two"})

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset1, prefix="prefix1_")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset2, prefix="prefix2_")

    form = SelectColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
        ("flex_fields__field1", "prefix1_Field One"),
        ("flex_fields__field2", "prefix2_Field Two"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_no_prefix_when_with_fs_prefix_false(monkeypatch):
    checker = DataCheckerFactory()
    form = SelectColumnsForm(checker=checker)

    assert form.fields["columns"].choices is not None


def test_init_with_checker_field_without_label_uses_field_name():
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()

    char_field_def = FieldDefinitionFactory(field_type=forms.CharField)

    FlexFieldFactory(fieldset=fieldset, name="field_without_label", definition=char_field_def, attrs={})

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="test_")

    form = SelectColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
        ("flex_fields__field_without_label", "test_field_without_label"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_field_with_empty_label_uses_field_name():
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()

    char_field_def = FieldDefinitionFactory(field_type=forms.CharField)

    FlexFieldFactory(fieldset=fieldset, name="field_with_empty_label", definition=char_field_def, attrs={"label": ""})

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="test_")

    form = SelectColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
        ("flex_fields__field_with_empty_label", "test_field_with_empty_label"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_field_with_none_label_uses_field_name():
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()

    char_field_def = FieldDefinitionFactory(field_type=forms.CharField)

    FlexFieldFactory(fieldset=fieldset, name="field_with_none_label", definition=char_field_def, attrs={"label": None})

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="test_")

    form = SelectColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
        ("flex_fields__field_with_none_label", "test_field_with_none_label"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_no_fieldsets_returns_only_core_fields():
    checker = DataCheckerFactory()

    form = SelectColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_empty_fieldset_returns_only_core_fields():
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="test_")

    form = SelectColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_inherits_from_select_columns_form():
    assert issubclass(SelectIndividualColumnsForm, SelectColumnsForm)


def test_has_individual_specific_core_fields():
    checker = DataCheckerFactory()

    form = SelectIndividualColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
        ("household", "household"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_creates_choices_with_prefix_and_household_field():
    checker = DataCheckerFactory()
    fieldset = FieldsetFactory()

    char_field_def = FieldDefinitionFactory(field_type=forms.CharField)

    FlexFieldFactory(
        fieldset=fieldset, name="individual_field", definition=char_field_def, attrs={"label": "Individual Field"}
    )

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix="ind_")

    form = SelectIndividualColumnsForm(checker=checker)

    expected_choices = [
        ("name", "name"),
        ("id", "id"),
        ("household", "household"),
        ("flex_fields__individual_field", "ind_Individual Field"),
    ]

    assert form.fields["columns"].choices == expected_choices


def test_init_with_checker_ordering_by_fieldset_id_and_prefix():
    checker = DataCheckerFactory()

    fieldset1 = FieldsetFactory()
    fieldset2 = FieldsetFactory()

    char_field_def = FieldDefinitionFactory(field_type=forms.CharField)

    FlexFieldFactory(fieldset=fieldset1, name="field1", definition=char_field_def, attrs={"label": "Field One"})
    FlexFieldFactory(fieldset=fieldset2, name="field2", definition=char_field_def, attrs={"label": "Field Two"})

    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset1, prefix="aaa")
    DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset2, prefix="bbb")

    form = SelectIndividualColumnsForm(checker=checker)

    flex_choices = [choice for choice in form.fields["columns"].choices if choice[0].startswith("flex_fields__")]

    expected_field_names = ["field1", "field2"]
    actual_field_names = [choice[0].replace("flex_fields__", "") for choice in flex_choices]

    assert actual_field_names == expected_field_names
