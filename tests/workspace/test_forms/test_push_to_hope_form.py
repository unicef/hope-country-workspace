import pytest
from typing import Any
from country_workspace.contrib.hope.forms import PushToHopeForm


HIDDEN_FORM_FIELDS = {
    "action": "push_to_hope",
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
    form = PushToHopeForm(data=post_data)
    assert form.is_valid() is expected_valid
    if expected_valid:
        assert form.cleaned_data["batch_name"] == data["batch_name"]
