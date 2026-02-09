from typing import TYPE_CHECKING

import pytest
from pytest_mock import MockerFixture
from django import forms
from django.urls import reverse
from strategy_field.utils import fqn
from testutils.factories import DataCheckerFactory
from testutils.perms import user_grant_permissions
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from hope_flex_fields.models import DataChecker
    from responses import RequestsMock
    from testutils.types import CWTestApp

    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def individual_checker():
    from testutils.factories import DataCheckerFactory, FieldsetFactory, FlexFieldFactory

    from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME

    dc = DataCheckerFactory(name=INDIVIDUAL_CHECKER_NAME)
    fs = FieldsetFactory()

    for field in ["address", "consent", "admin1", "zip_code"]:
        FlexFieldFactory(fieldset=fs, name=field)

    dc.fieldsets.add(fs)

    return dc


@pytest.fixture
def household_checker(request, active_marks):
    from testutils.factories import DataCheckerFactory, FieldsetFactory, FlexFieldFactory

    from country_workspace.contrib.hope.constants import HOUSEHOLD_CHECKER_NAME

    dc = DataCheckerFactory(name=HOUSEHOLD_CHECKER_NAME)
    fs = FieldsetFactory()

    for field in ["address", "admin1", "consent", "country_origin", "household_id"]:
        FlexFieldFactory(fieldset=fs, name=field)

    dc.fieldsets.add(fs)

    return dc


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={
            "address": "Cool address",
            "admin1": "",
            "consent": False,
            "country_origin": "",
        },
    )


@pytest.fixture
def individual(household: "CountryHousehold") -> "CountryIndividual":
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        batch=household.batch,
        household=household,
        batch__program=household.batch.program,
        batch__country_office=household.batch.program.country_office,
        flex_fields={
            "address": "Cool address",
            "admin1": "",
            "consent": "",
            "zip_code": "",
        },
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", mocked_responses: "RequestsMock") -> "CWTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_hh_changelist(app: "CWTestApp", household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    program: "CountryProgram" = household.program
    with select_office(app, program.country_office, program):
        res = app.get(url)
        assert res.status_code == 200, res.location
        assert f"Add {household._meta.verbose_name}" not in res.text
        # filter by program
        res = app.get(url)
        assert res.status_code == 200, res.location


def test_hh_change(app: "CWTestApp", household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
    program: "CountryProgram" = household.program
    with select_office(app, program.country_office, program):
        res = app.get(url)
        assert res.status_code == 200, res.location


def test_hh_validate_single(app: "CWTestApp", household: "CountryHousehold") -> None:
    with select_office(app, household.country_office, household.program):
        with user_grant_permissions(app._user, ["workspaces.change_countryhousehold"], household.program):
            url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
            res = app.get(url)
            res = res.click("Validate")
            res = res.follow()
            assert res.status_code == 200


def test_hh_validate_single_runs_alien_check(
    app: "CWTestApp", household: "CountryHousehold", mocker: MockerFixture
) -> None:
    mocker.patch(
        "country_workspace.admin.household.validate_alien_fields",
        side_effect=ValueError("Alien values found for: {'alien_field'}"),
    )
    with select_office(app, household.country_office, household.program):
        with user_grant_permissions(app._user, ["workspaces.change_countryhousehold"], household.program):
            url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
            res = app.get(url)
            res = res.click("Validate")
            res = res.follow()
            assert "Alien values found for" in res.text


def test_individual_validate_single_runs_alien_check(
    app: "CWTestApp", individual: "CountryIndividual", mocker: MockerFixture
) -> None:
    mocker.patch(
        "country_workspace.admin.individual.validate_alien_fields",
        side_effect=ValueError("Alien values found for: {'alien_field'}"),
    )
    with select_office(app, individual.country_office, individual.program):
        with user_grant_permissions(app._user, ["workspaces.change_countryindividual"], individual.program):
            url = reverse("workspace:workspaces_countryindividual_change", args=[individual.pk])
            res = app.get(url)
            res = res.click("Validate")
            res = res.follow()
            assert "Alien values found for" in res.text


def test_hh_update_single(app: "CWTestApp", household: "CountryHousehold") -> None:
    with select_office(app, household.country_office, household.program):
        with user_grant_permissions(app._user, ["workspaces.change_countryhousehold"], household.program):
            url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
            res = app.get(url)
            assert res.status_code == 200


def test_hh_validate_program(app: "CWTestApp", individual: "CountryIndividual"):
    program: "CountryProgram" = individual.program
    assert not individual.last_checked

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryhousehold_changelist")
        res = app.get(url)
        res.click("Validate Program").follow()

        individual.refresh_from_db()
        if program.beneficiary_group.master_detail:
            assert individual.household.last_checked
        assert individual.last_checked


@pytest.fixture
def hh_with_address(household) -> "CountryHousehold":
    dc: DataChecker = DataCheckerFactory(fields=[("address", fqn(forms.CharField))])
    fld = dc.fieldsets.first().fields.get(name="address")
    fld.attrs["required"] = True
    fld.save()
    household.flex_fields["address"] = None
    household.members.all().delete()
    household.save()

    household.program.household_checker = dc
    household.program.save()

    return household


def test_hh_validate(app: "CWTestApp", hh_with_address: "CountryHousehold"):
    assert not hh_with_address.validate_with_checker()
    assert hh_with_address.errors == {"address": ["This field is required."]}

    hh_with_address.flex_fields["address"] = "abc"
    hh_with_address.save()
    assert hh_with_address.validate_with_checker()
    assert hh_with_address.errors == {}


@pytest.fixture
def hh_with_check_initial(household) -> "CountryHousehold":
    dc: DataChecker = DataCheckerFactory(fields=[("field_to_check_initial", fqn(forms.CharField))])
    fields = dc.fieldsets.first().fields
    fields.filter(name="field_to_check_initial").update(attrs={"initial": "--unknown--"})

    household.program.household_checker = dc
    household.program.save()

    return household


def test_hh_initial_field(app: "CWTestApp", hh_with_check_initial: "CountryHousehold"):
    form_dc = hh_with_check_initial.program.household_checker.get_form_class()()
    value = form_dc.fields["field_to_check_initial"].initial

    url = reverse("workspace:workspaces_countryhousehold_change", args=[hh_with_check_initial.pk])
    with select_office(app, hh_with_check_initial.country_office, hh_with_check_initial.program):
        res = app.get(url)
        form_hh = res.forms["countryhousehold_form"]
        value_expected = form_hh["flex_field-field_to_check_initial"].value

    assert value == value_expected
