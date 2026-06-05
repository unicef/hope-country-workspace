import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import freezegun
import pytest
from django.urls import reverse
from pytest_mock import MockerFixture
from testutils.utils import select_office

from country_workspace.models import Household, Individual
from country_workspace.state import state
from country_workspace.workspaces.admin.cleaners import validate as validate_mod
from country_workspace.workspaces.admin.cleaners.validate import (
    ARCHIVED_UNIQUE_VALIDATION_ERROR,
    UNIQUE_VALIDATION_ERROR,
    UniqueValidationState,
    _append_household_member_invalid_error,
    _append_unique_error,
    _build_unique_state,
    _normalize_unique_value,
    _validate_and_count,
    validate_queryset,
)

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import SettingsWrapper

    from country_workspace.models import AsyncJob
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program, batch__country_office=program.country_office, flex_fields={"size": 5}
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_ws_validate(
    app: "DjangoTestApp", force_migrated_records, settings: "SettingsWrapper", household: "CountryHousehold"
) -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with freezegun.freeze_time("2020-01-01 00:00:00"):
        with select_office(app, household.country_office, household.program):
            res = app.get(url)
            form = res.forms["changelist-form"]
            form.set("_selected_action", True)
            form["action"].select("validate_records")
            res = form.submit()
            assert res.status_code == 302

            job: "AsyncJob" = household.program.jobs.first()
            assert job is not None
            household.refresh_from_db()
            assert household.last_checked.date() == datetime.date(2020, 1, 1)
            assert household.errors


@pytest.mark.django_db
def test_validate_queryset_empty_queryset(program, force_migrated_records):
    """Test validate_queryset with an empty queryset returns zeros."""
    empty_qs = Household.objects.none()
    result = validate_queryset(empty_qs)
    assert result == {"valid": 0, "invalid": 0}


@pytest.mark.django_db
def test_validate_queryset_individuals(program, force_migrated_records):
    """Test validate_queryset processes Individual queryset (else branch)."""
    from testutils.factories import IndividualFactory

    # Create some individuals
    ind1: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={
            "birth_date": "1990-01-01",
            "full_name": "John Doe",
        },
    )
    ind2: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={
            "birth_date": "1985-05-15",
            "full_name": "Jane Smith",
        },
    )

    qs = Individual.objects.filter(pk__in=[ind1.pk, ind2.pk])

    result = validate_queryset(qs)

    assert result["valid"] + result["invalid"] == 2


@pytest.mark.django_db
def test_validate_queryset_individual_unique_field_duplicates(program, force_migrated_records):
    from testutils.factories import IndividualFactory

    program.save_unique_field_for(Individual, "full_name")

    ind1: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"full_name": "John Doe"},
    )
    ind2: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"full_name": "John Doe"},
    )

    result = validate_queryset(Individual.objects.filter(pk__in=[ind1.pk, ind2.pk]))

    assert result == {"valid": 0, "invalid": 2}
    ind1.refresh_from_db()
    ind2.refresh_from_db()
    assert "full_name" in ind1.errors
    assert "full_name" in ind2.errors


@pytest.mark.django_db
def test_validate_queryset_individual_unique_field_against_archived_values(program, force_migrated_records):
    from testutils.factories import IndividualFactory

    program.save_unique_field_for(Individual, "full_name")
    program.add_removed_unique_values_for(Individual, ["John Doe"])

    individual: "CountryIndividual" = IndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"full_name": "John Doe"},
    )

    result = validate_queryset(Individual.objects.filter(pk=individual.pk))

    assert result == {"valid": 0, "invalid": 1}
    individual.refresh_from_db()
    assert "full_name" in individual.errors


@pytest.mark.django_db
def test_validate_queryset_households_marks_invalid_when_member_unique_duplicates(program, force_migrated_records):
    from testutils.factories import HouseholdFactory, IndividualFactory

    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.save_unique_field_for(Individual, "full_name")

    household: "CountryHousehold" = HouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 2},
    )
    IndividualFactory(
        household=household,
        batch=household.batch,
        flex_fields={"full_name": "Member X"},
    )
    IndividualFactory(
        household=household,
        batch=household.batch,
        flex_fields={"full_name": "Member X"},
    )

    result = validate_queryset(Household.objects.filter(pk=household.pk).prefetch_related("members"))
    assert result == {"valid": 0, "invalid": 1}

    household.refresh_from_db()
    assert "dct" in household.errors


@pytest.mark.django_db
def test_validate_queryset_households_marks_both_invalid_for_member_unique_duplicates_across_households(
    program, force_migrated_records
):
    from testutils.factories import HouseholdFactory, IndividualFactory

    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.save_unique_field_for(Individual, "full_name")

    hh1: "CountryHousehold" = HouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 1},
    )
    IndividualFactory(household=hh1, batch=hh1.batch, flex_fields={"full_name": "Member X"})

    hh2: "CountryHousehold" = HouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 1},
    )
    IndividualFactory(household=hh2, batch=hh2.batch, flex_fields={"full_name": "Member X"})

    result = validate_queryset(Household.objects.filter(pk__in=[hh1.pk, hh2.pk]), chunk_size=1)

    assert result == {"valid": 0, "invalid": 2}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("hello", "hello"),
        ("  spaced  ", "spaced"),
        (123, "123"),
    ],
)
def test_normalize_unique_value(raw: object, expected: str | None) -> None:
    assert _normalize_unique_value(raw) == expected


def _mock_obj(errors: object = None) -> MagicMock:
    obj = MagicMock()
    obj.errors = errors
    return obj


def test_append_unique_error_appends_first_message() -> None:
    obj = _mock_obj({})

    _append_unique_error(obj, "national_id", UNIQUE_VALIDATION_ERROR)

    assert obj.errors["national_id"] == [UNIQUE_VALIDATION_ERROR]
    obj.save.assert_called_once_with(update_fields=["errors", "last_checked"])


def test_append_unique_error_wraps_non_list_current() -> None:
    obj = _mock_obj({"national_id": "previous"})

    _append_unique_error(obj, "national_id", UNIQUE_VALIDATION_ERROR)

    assert obj.errors["national_id"] == ["previous", UNIQUE_VALIDATION_ERROR]


def test_append_unique_error_skips_when_message_already_present() -> None:
    obj = _mock_obj({"national_id": [UNIQUE_VALIDATION_ERROR]})

    _append_unique_error(obj, "national_id", UNIQUE_VALIDATION_ERROR)

    assert obj.errors == {"national_id": [UNIQUE_VALIDATION_ERROR]}
    obj.save.assert_not_called()


def test_append_household_member_invalid_error_appends() -> None:
    obj = _mock_obj({})

    _append_household_member_invalid_error(obj)

    assert obj.errors["dct"] == ["Some members did not validate"]
    obj.save.assert_called_once_with(update_fields=["errors", "last_checked"])


def test_append_household_member_invalid_error_wraps_non_list() -> None:
    obj = _mock_obj({"dct": "scalar"})

    _append_household_member_invalid_error(obj)

    assert obj.errors["dct"] == ["scalar", "Some members did not validate"]


def test_append_household_member_invalid_error_skips_when_marker_present() -> None:
    obj = _mock_obj({"dct": ["Some members did not validate"]})

    _append_household_member_invalid_error(obj)

    obj.save.assert_not_called()


def test_unique_validation_state_skips_empty_values() -> None:
    state_ = UniqueValidationState(field_name="national_id", archived_values=set())
    obj = MagicMock(flex_fields={"national_id": "  "})

    assert state_.validate(obj) == set()


def test_unique_validation_state_handles_missing_flex_fields() -> None:
    state_ = UniqueValidationState(field_name="national_id", archived_values=set())
    obj = MagicMock(flex_fields=None)

    assert state_.validate(obj) == set()


def test_unique_validation_state_archived_value(mocker: MockerFixture) -> None:
    spy = mocker.patch.object(validate_mod, "_append_unique_error")
    state_ = UniqueValidationState(field_name="national_id", archived_values={"A"})
    obj = MagicMock(pk=1, flex_fields={"national_id": "A"})

    assert state_.validate(obj) == {1}

    spy.assert_called_once_with(obj, "national_id", ARCHIVED_UNIQUE_VALIDATION_ERROR)


def test_unique_validation_state_first_occurrence_records_value() -> None:
    state_ = UniqueValidationState(field_name="national_id", archived_values=set())
    obj = MagicMock(pk=1, flex_fields={"national_id": "A"})

    assert state_.validate(obj) == set()
    assert state_.seen_by_value == {"A": obj}


def test_unique_validation_state_duplicate_marks_both(mocker: MockerFixture) -> None:
    spy = mocker.patch.object(validate_mod, "_append_unique_error")
    state_ = UniqueValidationState(field_name="national_id", archived_values=set())
    first = MagicMock(pk=1, flex_fields={"national_id": "A"})
    second = MagicMock(pk=2, flex_fields={"national_id": "A"})

    state_.validate(first)
    invalid = state_.validate(second)

    assert invalid == {1, 2}
    assert spy.call_count == 2
    assert spy.call_args_list[0].args == (first, "national_id", UNIQUE_VALIDATION_ERROR)
    assert spy.call_args_list[1].args == (second, "national_id", UNIQUE_VALIDATION_ERROR)


def test_build_unique_state_returns_none_when_no_field() -> None:
    program = MagicMock()
    program.get_unique_field_for.return_value = None

    assert _build_unique_state(program, Individual) is None


def test_build_unique_state_filters_falsy_archived_values() -> None:
    program = MagicMock()
    program.get_unique_field_for.return_value = "national_id"
    program.get_removed_unique_values_for.return_value = ["A", "", "B"]

    state_ = _build_unique_state(program, Individual)

    assert state_ is not None
    assert state_.field_name == "national_id"
    assert state_.archived_values == {"A", "B"}


def test_validate_and_count_without_states(mocker: MockerFixture) -> None:
    mocker.patch.object(validate_mod, "validate_alien_fields")
    mocker.patch.object(validate_mod, "batch_ctx")
    obj = MagicMock(pk=1, batch_id=1)
    obj.validate_with_checker.return_value = True

    valid, invalid = _validate_and_count([obj])

    assert (valid, invalid) == (1, 0)


def test_validate_and_count_invalid_obj_only(mocker: MockerFixture) -> None:
    mocker.patch.object(validate_mod, "validate_alien_fields")
    mocker.patch.object(validate_mod, "batch_ctx")
    obj = MagicMock(pk=1, batch_id=1)
    obj.validate_with_checker.return_value = False

    valid, invalid = _validate_and_count([obj])

    assert (valid, invalid) == (0, 1)


def test_validate_and_count_member_unique_only_for_household(mocker: MockerFixture) -> None:
    mocker.patch.object(validate_mod, "validate_alien_fields")
    mocker.patch.object(validate_mod, "batch_ctx")
    member_state = MagicMock(spec=UniqueValidationState)
    member_state.validate.return_value = set()
    obj = MagicMock(pk=1, batch_id=1)
    obj.validate_with_checker.return_value = True

    valid, invalid = _validate_and_count([obj], member_unique_state=member_state)

    assert (valid, invalid) == (1, 0)
    member_state.validate.assert_not_called()
