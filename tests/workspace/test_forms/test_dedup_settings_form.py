from django import forms

from country_workspace.workspaces.admin.forms import DedupSettingsForm


def test_dedup_settings_form_init() -> None:
    settings = {"threshold_1": 0.1, "threshold_2": 0.2}

    form = DedupSettingsForm(settings=settings)

    assert set(form.fields) == {"threshold_1", "threshold_2"}

    field = form.fields["threshold_1"]
    assert isinstance(field, forms.FloatField)
    assert field.min_value == 0
    assert field.max_value == 1
    assert field.required is True
    assert field.initial == 0.1
    assert isinstance(field.widget, forms.NumberInput)
    assert field.widget.attrs["step"] == "0.01"


def test_dedup_settings_form_get_payload() -> None:
    form = DedupSettingsForm(
        data={"threshold_1": "0.11", "threshold_2": "0.22"},
        settings={"threshold_1": 0.1, "threshold_2": 0.2},
    )

    assert form.is_valid()
    assert form.get_payload() == {"threshold_1": 0.11, "threshold_2": 0.22}
