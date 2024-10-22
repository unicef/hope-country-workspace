from typing import TYPE_CHECKING

from django.urls import reverse

import pytest
from pytest_django.fixtures import SettingsWrapper
from testutils.factories import DataCheckerFactory

from country_workspace.constants import HOUSEHOLD_CHECKER_NAME
from country_workspace.state import state
from country_workspace.workspaces.admin.actions.mass_update import mass_update_impl

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryHousehold

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture()
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    yield co


@pytest.fixture()
def program(office, force_migrated_records):
    from testutils.factories import CountryProgramFactory

    hdc = DataCheckerFactory(name=HOUSEHOLD_CHECKER_NAME)
    return CountryProgramFactory(
        country_office=office,
        household_checker=hdc,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture()
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.fixture()
def app(
    django_app_factory: "MixinWithInstanceVariables",
    settings: SettingsWrapper,
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    yield django_app


@pytest.mark.xfail()
def test_mass_update_impl(household):
    from country_workspace.models import Household

    mass_update_impl(Household.objects.all(), {"address": ("djangoformsfieldsfield_set_lambda", "__NEW VALUE__")})

    household.refresh_from_db()
    assert household.flex_fields["address"] == "__NEW VALUE__"


@pytest.mark.xfail()
def test_mass_update(app: "DjangoTestApp", household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = household.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(f"{url}?batch__program__exact={household.program.pk}")
    form = res.forms["changelist-form"]
    form["action"] = "mass_update"
    form.set("_selected_action", True, 0)
    res = form.submit()

    form = res.forms["mass-update-form"]
    form["flex_fields__address_0"].select(text="set")
    form["flex_fields__address_1"] = "__NEW VALUE__"
    res = form.submit("_apply")

    household.refresh_from_db()
    assert household.flex_fields["address"] == "__NEW VALUE__"
