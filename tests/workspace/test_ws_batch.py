from typing import TYPE_CHECKING

from django.urls import reverse

import pytest
from responses import RequestsMock
from testutils.utils import select_office

from country_workspace.constants import HOUSEHOLD_CHECKER_NAME, INDIVIDUAL_CHECKER_NAME
from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.workspaces.models import CountryBatch

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture()
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    yield co


@pytest.fixture()
def program(office):
    from testutils.factories import CountryProgramFactory, DataCheckerFactory

    return CountryProgramFactory(
        household_checker=DataCheckerFactory(name=HOUSEHOLD_CHECKER_NAME),
        individual_checker=DataCheckerFactory(name=INDIVIDUAL_CHECKER_NAME),
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture()
def batch(program):
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)
    return hh.batch


@pytest.fixture()
def app(django_app_factory: "MixinWithInstanceVariables", mocked_responses: "RequestsMock") -> "CWTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    yield django_app


def test_batch_changelist(app: "CWTestApp", batch: "CountryBatch") -> None:
    url = reverse("workspace:workspaces_countrybatch_changelist")
    with select_office(app, batch.program.country_office):
        # res = app.get(url).follow()
        # res.forms["select-tenant"]["tenant"] = household.country_office.pk
        # res.forms["select-tenant"].submit()
        res = app.get(url)
        assert res.status_code == 200, res.location
        assert f"Add {batch._meta.verbose_name}" not in res.text
        # filter by program
        res = app.get(f"{url}?program__exact={batch.program.pk}")
        assert res.status_code == 200, res.location
        assert res.status_code == 200, res.location


#
# def test_hh_change(app: "CWTestApp", household: "CountryHousehold") -> None:
#     url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
#     res = app.get(url).follow()
#     res.forms["select-tenant"]["tenant"] = household.country_office.pk
#     res.forms["select-tenant"].submit()
#
#     res = app.get(f"{url}?batch__program__exact={household.program.pk}")
#     assert res.status_code == 200, res.location
#     assert f"Change {household._meta.verbose_name}" in res.text
#     res = res.forms["countryhousehold_form"].submit()
#     assert res.status_code == 302, res.location
#
#
# def test_hh_delete(app: "CWTestApp", household: "CountryHousehold") -> None:
#     url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
#     res = app.get(url).follow()
#     res.forms["select-tenant"]["tenant"] = household.country_office.pk
#     res.forms["select-tenant"].submit()
#     res = app.get(f"{url}?batch__program__exact={household.program.pk}")
#     assert res.status_code == 200, res.location
#     res = res.click("Delete")
#     res = res.forms[1].submit().follow()
#     assert res.status_code == 200
#     with pytest.raises(ObjectDoesNotExist):
#         household.refresh_from_db()
#
#
# def test_hh_validate_single(app: "CWTestApp", household: "CountryHousehold") -> None:
#     res = app.get("/").follow()
#     res.forms["select-tenant"]["tenant"] = household.country_office.pk
#     res.forms["select-tenant"].submit()
#     with user_grant_permissions(app._user, ["workspaces.change_countryhousehold"], household.program):
#         url = reverse("workspace:workspaces_countryhousehold_change", args=[household.pk])
#         res = app.get(f"{url}?batch__program__exact={household.program.pk}")
#         res = res.click("Validate")
#         res = res.follow()
#         assert res.status_code == 200
#
#
# def test_hh_validate_program(app: "CWTestApp", household: "CountryHousehold") -> None:
#     res = app.get("/").follow()
#     res.forms["select-tenant"]["tenant"] = household.country_office.pk
#     res.forms["select-tenant"].submit()
#     with user_grant_permissions(app._user, ["workspaces.change_countryhousehold"], household.program):
#         url = reverse("workspace:workspaces_countryhousehold_changelist")
#         res = app.get(f"{url}?batch__program__exact={household.program.pk}")
#         res.click("Validate Programme").follow()
#         household.refresh_from_db()
#         assert household.last_checked
