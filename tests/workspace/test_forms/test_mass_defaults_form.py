from unittest.mock import MagicMock

from django import forms

from country_workspace.workspaces.admin.forms import MassDefaultsForm


def test_mass_defaults_form_initializes_fields_from_checker() -> None:
    class DummyCheckerForm(forms.Form):
        field1 = forms.CharField(required=True)
        field2 = forms.IntegerField()

    checker = MagicMock()
    checker.get_form.return_value = DummyCheckerForm

    form = MassDefaultsForm(checker=checker)

    checker.get_form.assert_called_once_with()
    assert set(form.fields.keys()) == {"field1", "field2"}
    assert isinstance(form.fields["field1"], forms.CharField)
    assert isinstance(form.fields["field2"], forms.IntegerField)
    assert form.fields["field1"].required is False
    assert form.fields["field2"].required is False


def test_mass_defaults_form_binds_data_via_base_form_init() -> None:
    class DummyCheckerForm(forms.Form):
        flag = forms.BooleanField(required=True)

    checker = MagicMock()
    checker.get_form.return_value = DummyCheckerForm

    form = MassDefaultsForm(data={"flag": "on"}, checker=checker)

    assert form.fields["flag"].required is False
    assert form.is_valid()
    assert form.cleaned_data["flag"] is True
