from typing import Any
import pytest
from unittest.mock import MagicMock
from pytest_mock import MockerFixture
from django.core.exceptions import ValidationError
from django.urls import Resolver404

from country_workspace.models import Office, Program, Batch, Household, Individual
from country_workspace.contrib.hope.beneficiary_reference import (
    _resolve_hh_batch_pks,
    BeneficiarySelect2Widget,
    BeneficiaryReferenceModelChoiceField,
    _KW_BY_VIEW,
)
from country_workspace.state import state

VIEW_NAME = next(iter(_KW_BY_VIEW.keys()))
MOD = "country_workspace.contrib.hope.beneficiary_reference"


@pytest.fixture
def office() -> Office:
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office: Office) -> Program:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(country_office=office)


@pytest.fixture
def batch(program: Program) -> Batch:
    from testutils.factories import BatchFactory

    return BatchFactory(program=program)


@pytest.fixture
def household(batch: Batch) -> Household:
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch=batch)


@pytest.fixture
def individual(household: Household) -> Individual:
    return household.members.first()


@pytest.fixture
def ambiguous_individuals(batch: Batch) -> tuple[Household, str]:
    from testutils.factories import CountryHouseholdFactory, IndividualFactory

    hh = CountryHouseholdFactory(batch=batch)
    dup_id = f"DUP-{hh.pk}"
    for _ in range(2):
        IndividualFactory(household=hh, removed=False, flex_fields={"individual_id": dup_id})

    return hh, dup_id


@pytest.mark.parametrize(
    ("has_request", "view_name", "kwargs", "row", "get_batch_val", "expected"),
    [
        (False, None, {}, None, 777, (None, 777)),
        (True, VIEW_NAME, {"object_id": "456"}, (456, 999), None, (456, 999)),
        (True, VIEW_NAME, {}, None, None, (None, None)),
        (True, "other_view", {"object_id": "456"}, None, None, (None, None)),
        (True, VIEW_NAME, {"object_id": "abc"}, None, None, (None, None)),
    ],
    ids=[
        "no_request",
        "valid_view_with_object_id",
        "valid_view_without_object_id",
        "different_view",
        "invalid_object_id",
    ],
)
def test_resolve_hh_batch_pks_success(
    mocker: MockerFixture,
    has_request: bool,
    view_name: str,
    kwargs: dict,
    row: tuple,
    get_batch_val: int,
    expected: tuple[int, int],
) -> None:
    apps = MagicMock()
    # apps.get_model(...).objects.filter(...).values_list(...).first() -> row
    apps.get_model.return_value.objects.filter.return_value.values_list.return_value.first.return_value = row
    mocker.patch.multiple(
        MOD,
        state=MagicMock(request=MagicMock(path="/some/path") if has_request else None),
        resolve=MagicMock(return_value=MagicMock(kwargs=kwargs, view_name=view_name)),
        get_batch=MagicMock(return_value=get_batch_val),
        apps=apps,
    )

    assert _resolve_hh_batch_pks() == expected


@pytest.mark.parametrize(
    "side_effect",
    [Resolver404("not found"), KeyError("missing"), TypeError("bad"), ValueError("bad")],
    ids=["Resolver404", "KeyError", "TypeError", "ValueError"],
)
def test_resolve_hh_batch_pks_exceptions(mocker: MockerFixture, side_effect: Exception) -> None:
    mocker.patch.multiple(
        MOD,
        state=MagicMock(request=MagicMock(path="/some/path")),
        resolve=MagicMock(side_effect=side_effect),
        get_batch=MagicMock(return_value=111),
    )
    assert _resolve_hh_batch_pks() == (None, None)


def test_beneficiary_widget_init() -> None:
    w = BeneficiarySelect2Widget(batch_id=123, household_id=456, limit_to_household=True)
    assert (w.batch_id, w.household_id, w.limit_to_hh) == (123, 456, True)
    assert w.attrs["data-minimum-input-length"] == 0
    assert w.attrs["class"] == "form-control"


@pytest.mark.django_db
@pytest.mark.parametrize("batch_id", [99999, None], ids=["non_existing_batch", "no_batch"])
def test_widget_get_queryset_returns_empty_for_invalid_or_missing_batch(batch_id: int | None) -> None:
    assert not BeneficiarySelect2Widget(batch_id=batch_id).get_queryset().exists()


@pytest.mark.django_db
def test_widget_get_queryset_with_batch_filter(batch: Batch, individual: Individual) -> None:
    qs = BeneficiarySelect2Widget(batch_id=batch.id).get_queryset()
    assert individual in qs
    assert all(obj.batch_id == batch.id for obj in qs)


@pytest.mark.django_db
def test_widget_value_from_datadict_resolves_household_code_to_pk(mocker: MockerFixture, batch: Batch) -> None:
    apps = MagicMock()
    # apps.get_model(...).objects.filter(...).values_list(...).first() -> 777
    apps.get_model.return_value.objects.filter.return_value.values_list.return_value.first.return_value = 777
    mocker.patch(f"{MOD}.apps", apps)

    w = BeneficiarySelect2Widget(batch_id=batch.id, limit_to_household=True, household_id=None)
    w.value_from_datadict(data={"household_id": "HH-CODE-001"}, files={}, name="beneficiary")

    assert w.household_id == 777


@pytest.mark.django_db
@pytest.mark.parametrize("has_batch", [True, False], ids=["with_batch", "without_batch"])
def test_field_init(mocker: MockerFixture, batch: Batch, individual: Individual, has_batch: bool) -> None:
    mocker.patch(
        f"{MOD}._resolve_hh_batch_pks",
        return_value=((None, batch.id) if has_batch else (None, None)),
    )

    field = BeneficiaryReferenceModelChoiceField()

    if has_batch:
        assert individual in field.queryset
        assert all(ind.batch_id == batch.id for ind in field.queryset)
        assert isinstance(field.widget, BeneficiarySelect2Widget)
        assert field.widget.batch_id == batch.id
    else:
        assert not field.queryset.exists()


@pytest.mark.django_db
def test_field_init_with_household_limit(mocker: MockerFixture, batch: Batch, household: Household) -> None:
    mocker.patch(f"{MOD}._resolve_hh_batch_pks", return_value=(household.id, batch.id))

    field = BeneficiaryReferenceModelChoiceField(limit_to_household=True)

    assert field.queryset.exists()
    assert all(getattr(ind, "household_id", None) == household.id for ind in field.queryset)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("build", "expect_none"),
    [
        ("none", True),
        ("blank", True),
        ("pk_str", False),
        ("pk_int", False),
        ("object", False),
    ],
    ids=["empty_none", "empty_blank", "pk_str_ok", "pk_int_ok", "object_ok"],
)
def test_to_python_success(
    mocker: MockerFixture, batch: Batch, individual: Individual, build: str, expect_none: bool
) -> None:
    mocker.patch(f"{MOD}._resolve_hh_batch_pks", return_value=(None, batch.id))
    field = BeneficiaryReferenceModelChoiceField()

    value = {
        "none": lambda: None,
        "blank": lambda: "",
        "pk_str": lambda: str(individual.pk),
        "pk_int": lambda: individual.pk,
        "object": lambda: individual,
    }[build]()
    out = field.to_python(value)

    assert (out is None) if expect_none else (getattr(out, "pk", None) == individual.pk)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("with_batch", "value"),
    [
        (True, "999999"),
        (True, "non-digit"),
        (True, ["invalid"]),
        (False, "any_value"),
    ],
    ids=["invalid_unknown_pk_str", "invalid_non_digit_str", "invalid_list", "empty_queryset"],
)
def test_to_python_failure(mocker: MockerFixture, batch: Batch, with_batch: bool, value: Any) -> None:
    mocker.patch(
        f"{MOD}._resolve_hh_batch_pks",
        return_value=(None, batch.id) if with_batch else (None, None),
    )
    field = BeneficiaryReferenceModelChoiceField()
    with pytest.raises(ValidationError):
        field.to_python(value)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("value_kind", "raw_super", "expected"),
    [
        ("object", False, "pk"),
        ("empty_none", False, None),
        ("empty_str", False, None),
        ("int_pk", True, "same"),
        ("str_pk", True, "same"),
    ],
    ids=["object", "empty_none", "empty_str", "int_pk_calls_super", "str_pk_calls_super"],
)
def test_prepare(
    mocker: MockerFixture, batch: Batch, individual: Individual, value_kind: str, raw_super: bool, expected: str
) -> None:
    mocker.patch(f"{MOD}._resolve_hh_batch_pks", return_value=(None, batch.id))
    field = BeneficiaryReferenceModelChoiceField()

    value = {
        "object": individual,
        "empty_none": None,
        "empty_str": "",
        "int_pk": individual.pk,
        "str_pk": str(individual.pk),
    }[value_kind]
    if raw_super:
        mock_super = mocker.patch.object(field.__class__.__bases__[0], "prepare_value", return_value=value)
    out = field.prepare_value(value)

    if expected == "pk":
        assert out == individual.pk
    elif expected == "same":
        assert out == value
        assert mock_super.call_count == 1
    else:
        assert out is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "required", "expected"),
    [
        ("pk", True, "pk"),
        ("obj", True, "pk"),
        ("", False, None),
        (None, False, None),
    ],
    ids=["valid_pk", "valid_object", "empty_string", "none"],
)
def test_clean_success(
    mocker: MockerFixture, batch: Batch, individual: Individual, kind: str, required: bool, expected: str
) -> None:
    mocker.patch(f"{MOD}._resolve_hh_batch_pks", return_value=(None, batch.id))
    field = BeneficiaryReferenceModelChoiceField()
    field.required = required

    value = {
        "pk": str(individual.pk),
        "obj": individual,
        "": "",
        None: None,
    }[kind]

    out = field.clean(value)
    assert (out == individual.pk) if expected == "pk" else (out is None)


@pytest.mark.django_db
@pytest.mark.parametrize("val", ["999999"], ids=["invalid_pk"])
def test_clean_failure(mocker: MockerFixture, batch: Batch, val: Any) -> None:
    mocker.patch(f"{MOD}._resolve_hh_batch_pks", return_value=(None, batch.id))
    field = BeneficiaryReferenceModelChoiceField()
    with pytest.raises(ValidationError):
        field.clean(val)
