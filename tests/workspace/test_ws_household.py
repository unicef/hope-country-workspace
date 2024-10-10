from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

import pytest
from pytest_django.fixtures import SettingsWrapper
from responses import RequestsMock

from country_workspace.state import state

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
def program(office):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture()
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        program=program, country_office=program.country_office
    )


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


def test_hh_changelist(app: "DjangoTestApp", household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = household.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(url)
    assert res.status_code == 200, res.location
    assert f"Add {household._meta.verbose_name}" not in res.text
    # filter by program
    res = app.get(f"{url}?program__exact={household.program.pk}")
    assert res.status_code == 200, res.location


def test_hh_change(app: "DjangoTestApp", household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = household.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(url)
    assert res.status_code == 200, res.location
    assert f"Change {household._meta.verbose_name}" in res.text
    res = res.forms["countryhousehold_form"].submit()
    assert res.status_code == 302, res.location


def test_hh_delete(app: "DjangoTestApp", household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
    res = app.get(url).follow()
    res.forms["select-tenant"]["tenant"] = household.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(url)
    assert res.status_code == 200, res.location
    res = res.click("Delete")
    res = res.forms[1].submit().follow()
    assert res.status_code == 200
    with pytest.raises(ObjectDoesNotExist):
        household.refresh_from_db()
