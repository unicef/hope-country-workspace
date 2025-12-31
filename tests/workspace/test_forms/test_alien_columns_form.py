from django import forms

from country_workspace.workspaces.admin.program import AlienColumnsForm


def test_form_has_new_columns_field():
    form = AlienColumnsForm()
    assert "new_columns" in form.fields
    assert isinstance(form.fields["new_columns"], forms.MultipleChoiceField)


def test_new_columns_field_not_required():
    form = AlienColumnsForm()
    assert form.fields["new_columns"].required is False


def test_new_columns_uses_select_multiple_widget():
    form = AlienColumnsForm()
    assert isinstance(form.fields["new_columns"].widget, forms.SelectMultiple)


def test_init_without_data_or_existing_columns():
    form = AlienColumnsForm()
    assert form.fields["new_columns"].choices == []


def test_init_with_data_sets_choices_from_new_columns():
    data = {"new_columns": ["col1", "col2", "col3"]}
    form = AlienColumnsForm(data=data)
    expected_choices = [("col1", "col1"), ("col2", "col2"), ("col3", "col3")]
    assert form.fields["new_columns"].choices == expected_choices


def test_init_with_existing_columns_sets_choices():
    existing = ["existing1", "existing2"]
    form = AlienColumnsForm(existing_columns=existing)
    expected_choices = [("existing1", "existing1"), ("existing2", "existing2")]
    assert form.fields["new_columns"].choices == expected_choices


def test_init_with_existing_columns_sets_initial_values():
    existing = ["existing1", "existing2"]
    form = AlienColumnsForm(existing_columns=existing)
    assert form.initial["new_columns"] == existing


def test_data_takes_priority_over_existing_columns():
    data = {"new_columns": ["from_data"]}
    existing = ["from_existing"]
    form = AlienColumnsForm(data=data, existing_columns=existing)
    expected_choices = [("from_data", "from_data")]
    assert form.fields["new_columns"].choices == expected_choices


def test_init_with_empty_data_uses_existing_columns():
    data = {}
    existing = ["existing1"]
    form = AlienColumnsForm(data=data, existing_columns=existing)
    expected_choices = [("existing1", "existing1")]
    assert form.fields["new_columns"].choices == expected_choices


def test_form_valid_with_no_selection():
    form = AlienColumnsForm(data={})
    assert form.is_valid()


def test_form_valid_with_valid_selection():
    data = {"new_columns": ["col1", "col2"]}
    form = AlienColumnsForm(data=data)
    assert form.is_valid()
    assert form.cleaned_data["new_columns"] == ["col1", "col2"]


def test_form_with_single_column():
    data = {"new_columns": ["single"]}
    form = AlienColumnsForm(data=data)
    assert form.fields["new_columns"].choices == [("single", "single")]


def test_form_with_empty_new_columns_list():
    data = {"new_columns": []}
    form = AlienColumnsForm(data=data)
    assert form.fields["new_columns"].choices == []


def test_existing_columns_empty_list():
    form = AlienColumnsForm(existing_columns=[])
    assert form.fields["new_columns"].choices == []
    assert form.initial.get("new_columns") is None


def test_kwargs_passed_to_parent():
    form = AlienColumnsForm(prefix="test")
    assert form.prefix == "test"
