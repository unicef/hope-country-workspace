from typing import TYPE_CHECKING

from django.urls import reverse

import pytest
from pytest_django.fixtures import SettingsWrapper
from responses import RequestsMock
from testutils.factories import DataCheckerFactory

from country_workspace.constants import HOUSEHOLD_CHECKER_NAME
from country_workspace.state import state
from country_workspace.workspaces.admin.actions.regex import regex_update_impl

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
    mocked_responses: "RequestsMock",
    settings: SettingsWrapper,
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    yield django_app


def test_regex_update_impl(household):
    from country_workspace.models import Household

    regex_update_impl(Household.objects.all(), {"field": "address", "regex": ".*", "subst": "__NEW VALUE__"})

    household.refresh_from_db()
    assert household.flex_fields["address"] == "__NEW VALUE__"


def test_regex_update(app: "DjangoTestApp", force_migrated_records, household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = household.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(f"{url}?batch__program__exact={household.program.pk}")
    form = res.forms["changelist-form"]
    form["action"] = "regex_update"
    form.set("_selected_action", True, 0)
    res = form.submit()

    form = res.forms["regex-update-form"]
    form["field"].select(text="address")
    form["regex"] = ".*"
    form["subst"] = "__NEW VALUE__"
    form.submit("_preview")

    household.refresh_from_db()
    assert household.flex_fields["address"] == "__NEW VALUE__"
