import pytest
from typing import Any

from country_workspace.contrib.hope.forms import CreateRDPForm, CreateRDPushThresholdForm


HIDDEN_FORM_FIELDS = {
    "action": "create_rdp",
    "select_across": "0",
    "_selected_action": "1",
}


@pytest.mark.parametrize(
    ("data", "expected_valid"),
    [
        ({"batch_name": "test"}, True),
        ({"batch_name": ""}, True),
    ],
    ids=["valid_with_name", "valid_with_empty_name"],
)
def test_form_valid_and_cleaned(data: dict[str, Any], expected_valid: bool) -> None:
    post_data = {**HIDDEN_FORM_FIELDS, **{k: str(v) for k, v in data.items()}}
    form = CreateRDPForm(data=post_data)
    assert form.is_valid() is expected_valid
    if expected_valid:
        assert form.cleaned_data["batch_name"] == data["batch_name"]


def test_push_to_hope_field_hidden_by_default() -> None:
    form = CreateRDPForm()
    assert "push_to_hope" not in form.fields


def test_push_to_hope_field_visible_with_show_push_option() -> None:
    form = CreateRDPForm(show_push_option=True)
    assert "push_to_hope" in form.fields
    assert "push_error_threshold_percent" not in form.fields


@pytest.mark.parametrize(
    ("push_to_hope", "expected"),
    [(True, True), (False, False)],
    ids=["checked", "unchecked"],
)
def test_push_to_hope_field_valid_when_shown(push_to_hope: bool, expected: bool) -> None:
    post_data = {
        **HIDDEN_FORM_FIELDS,
        "batch_name": "test",
        "push_to_hope": "on" if push_to_hope else "",
    }
    form = CreateRDPForm(data=post_data, show_push_option=True)
    assert form.is_valid()
    assert form.cleaned_data["push_to_hope"] is expected


def test_push_threshold_form_has_only_threshold_visible() -> None:
    form = CreateRDPushThresholdForm()
    assert set(form.fields) == {
        "action",
        "select_across",
        "_selected_action",
        "batch_name",
        "push_to_hope",
        "max_dedup_findings_percent",
    }


def test_push_threshold_form_has_no_validation_error_threshold() -> None:
    form = CreateRDPushThresholdForm()
    assert "push_error_threshold_percent" not in form.fields


@pytest.mark.parametrize("max_findings", ["0", "10", "100"])
def test_push_threshold_form_max_dedup_findings_valid_values(max_findings: str) -> None:
    post_data = {
        **HIDDEN_FORM_FIELDS,
        "batch_name": "Batch",
        "push_to_hope": "on",
        "max_dedup_findings_percent": max_findings,
    }
    form = CreateRDPushThresholdForm(data=post_data)
    assert form.is_valid()
    assert form.cleaned_data["max_dedup_findings_percent"] == int(max_findings)


def test_push_threshold_form_max_dedup_findings_optional() -> None:
    """max_dedup_findings_percent is optional — omitting it is valid."""
    post_data = {
        **HIDDEN_FORM_FIELDS,
        "batch_name": "Batch",
        "push_to_hope": "on",
    }
    form = CreateRDPushThresholdForm(data=post_data)
    assert form.is_valid()
    assert form.cleaned_data.get("max_dedup_findings_percent") is None


@pytest.mark.parametrize("invalid_value", ["-1", "101"])
def test_push_threshold_form_max_dedup_findings_out_of_range(invalid_value: str) -> None:
    post_data = {
        **HIDDEN_FORM_FIELDS,
        "batch_name": "Batch",
        "push_to_hope": "on",
        "max_dedup_findings_percent": invalid_value,
    }
    form = CreateRDPushThresholdForm(data=post_data)
    assert not form.is_valid()
    assert "max_dedup_findings_percent" in form.errors
