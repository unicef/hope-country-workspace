import pytest
from typing import Any
from country_workspace.contrib.hope.forms import PushToHopeForm
from country_workspace.workspaces.models import CountryProgram
from country_workspace.models import Office

from country_workspace.state import state
from testutils.factories import OfficeFactory, CountryProgramFactory, DataCheckerFactory


HIDDEN_FORM_FIELDS = {
    "action": "push_to_hope",
    "select_across": "0",
    "_selected_action": "1",
}


@pytest.fixture
def office() -> Office:
    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(request: pytest.FixtureRequest, office: Office) -> CountryProgram:
    return CountryProgramFactory(
        country_office=office,
        household_checker=DataCheckerFactory(fields=["a"]),
        individual_checker=DataCheckerFactory(fields=["b"]),
        beneficiary_group__master_detail=request.param,
    )


@pytest.mark.parametrize(
    ("data", "expected_valid", "expected_size"),
    [
        ({"batch_name": "test", "batch_size": 10}, True, 10),
        ({"batch_name": "", "batch_size": ""}, True, None),
    ],
    ids=["valid_with_name_size", "valid_empty"],
)
def test_form_valid_and_cleaned(
    program: CountryProgram, data: dict[str, Any], expected_valid: bool, expected_size: int | None
) -> None:
    post_data = {**HIDDEN_FORM_FIELDS, **{k: str(v) for k, v in data.items()}}
    form = PushToHopeForm(data=post_data, program=program)
    assert form.is_valid() is expected_valid
    if expected_valid:
        assert form.cleaned_data["batch_name"] == data["batch_name"]
        assert form.cleaned_data["batch_size"] == expected_size


@pytest.mark.parametrize("use_program", [True, False], ids=["with_program", "no_program"])
def test_batch_size_help_text(program: CountryProgram, use_program: bool) -> None:
    post_data = HIDDEN_FORM_FIELDS.copy()
    form = PushToHopeForm(data=post_data, program=program if use_program else None)
    if use_program:
        bg = program.beneficiary_group
        label = bg.group_label_plural if bg.master_detail else bg.member_label_plural
        expected = f"Number of {label} to push in each batch"
    else:
        expected = "Number of beneficiaries to push in each batch"
    assert form.fields["batch_size"].help_text == expected
