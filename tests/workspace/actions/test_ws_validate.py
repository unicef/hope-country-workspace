import datetime
from typing import TYPE_CHECKING

import freezegun
import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.models import Household, Individual
from country_workspace.state import state
from country_workspace.workspaces.admin.cleaners.validate import validate_queryset

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
