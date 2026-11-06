from uuid import UUID

import pytest
from django.http import QueryDict

from country_workspace.models import RdpOperation
from country_workspace.rdp.forms import CleanRdpForm, RdpFindingsFilterForm
from country_workspace.rdp.ocr.types import OcrFindingType
from country_workspace.rdp.types import OperationLogResult


pytestmark = pytest.mark.django_db


@pytest.fixture
def operations(
    successful_biometric_operation: RdpOperation, successful_ocr_operation: RdpOperation
) -> list[tuple[RdpOperation, OperationLogResult]]:
    return [(successful_biometric_operation, {"findings_count": 2}), (successful_ocr_operation, {"findings_count": 1})]


@pytest.mark.parametrize("include_household", [True, False])
def test_findings_filter_form(include_household: bool) -> None:
    data = QueryDict(f"finding_type={OcrFindingType.NO_MATCH}&individual_id=1&household_id=2&latest_only=1")
    form = RdpFindingsFilterForm(data, finding_types=OcrFindingType.choices, include_household=include_household)

    assert form.is_valid()
    assert form.cleaned_data["finding_type"] == OcrFindingType.NO_MATCH
    assert form.cleaned_data["individual_id"] == 1
    assert form.cleaned_data["latest_only"] is True
    assert ("household_id" in form.fields) is include_household
    assert form.cleaned_data.get("household_id") == (2 if include_household else None)


def test_findings_filter_form_accepts_empty_filters() -> None:
    form = RdpFindingsFilterForm(QueryDict(), finding_types=OcrFindingType.choices)

    assert form.is_valid()
    assert form.cleaned_data == {"finding_type": "", "individual_id": None, "household_id": None, "latest_only": False}


@pytest.mark.parametrize("field", ["individual_id", "household_id"])
@pytest.mark.parametrize(("value", "code"), [("0", "min_value"), (str(2**63), "max_value")])
def test_findings_filter_form_rejects_invalid_id(field: str, value: str, code: str) -> None:
    form = RdpFindingsFilterForm(QueryDict(f"{field}={value}"), finding_types=OcrFindingType.choices)

    assert form.has_error(field, code)


def test_findings_filter_form_rejects_unknown_type() -> None:
    form = RdpFindingsFilterForm(QueryDict("finding_type=unknown"), finding_types=OcrFindingType.choices)

    assert form.has_error("finding_type", "invalid_choice")


def test_clean_rdp_form_initial_selection(operations: list[tuple[RdpOperation, OperationLogResult]]) -> None:
    form = CleanRdpForm(operations=operations)

    assert form.initial["clean_operations"] == [str(operation.pk) for operation, __ in operations]


def test_clean_rdp_form_returns_selected_uuids(operations: list[tuple[RdpOperation, OperationLogResult]]) -> None:
    selected = operations[1][0].pk
    form = CleanRdpForm({"clean_operations": [str(selected)]}, operations=operations)

    assert form.is_valid()
    assert form.cleaned_data["clean_operations"] == [selected]


@pytest.mark.parametrize(
    ("values", "code"),
    [([], "required"), ([str(UUID(int=0))], "invalid_choice")],
)
def test_clean_rdp_form_rejects_invalid_selection(
    operations: list[tuple[RdpOperation, OperationLogResult]], values: list[str], code: str
) -> None:
    form = CleanRdpForm({"clean_operations": values}, operations=operations)

    assert form.has_error("clean_operations", code)
