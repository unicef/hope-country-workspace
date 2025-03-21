from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import SettingsWrapper
    from responses import RequestsMock

    from country_workspace.models import Household


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(request, office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
        beneficiary_group__master_detail=request.param,
    )


@pytest.fixture
def user():
    from testutils.factories import UserFactory

    return UserFactory(is_staff=True)


@pytest.fixture
def data(program):
    from testutils.factories import HouseholdFactory

    households = HouseholdFactory.create_batch(
        10,
        batch__program=program,
        batch__country_office=program.country_office,
    )
    for hh in households:
        hh.members.update(last_checked=timezone.now(), errors={})
    return households


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", mocked_responses: "RequestsMock") -> "DjangoTestApp":
    django_app = django_app_factory(csrf_checks=False)
    state.reset()
    return django_app


def test_login(app, user, data: "list[Household]", settings: "SettingsWrapper", program):
    from testutils.perms import user_grant_permissions

    settings.FLAGS = {"LOCAL_LOGIN": [("boolean", True)]}

    home = reverse("workspace:index")
    res = app.get(home)
    assert res.status_code == 302
    assert res.location == reverse("workspace:login")
    res = res.follow()
    res.forms["login-form"]["username"] = user.username
    res.forms["login-form"]["password"] = user._password
    res = res.forms["login-form"].submit()
    assert res.status_code == 302
    assert res.location == reverse("workspace:select_tenant")
    res = res.follow()
    assert "You do not have any Office enabled." in res.text

    with user_grant_permissions(
        user,
        ["workspaces.view_countryhousehold", "workspaces.view_countryindividual", "workspaces.view_countryprogram"],
        program.country_office,
    ):
        hh = data[0]
        res = app.get(reverse("workspace:select_tenant"), user=user)
        res.forms["select-tenant"]["tenant"] = program.country_office.pk
        res = res.forms["select-tenant"].submit().follow()
        assert app.cookies["selected_tenant"] == program.country_office.slug

        res.forms["select-program"]["program"].force_value(program.pk)
        res = res.forms["select-program"].submit().follow()

        if program.beneficiary_group.master_detail:
            res = res.click(program.beneficiary_group.group_label_plural)
            res = res.click(hh.name)
        else:
            res = res.click(program.beneficiary_group.member_label_plural)
            res = res.click("Show all")
            individual = hh.members.order_by("?").first()
            res = res.click(individual.name)

        res.click("Close", verbose=True)
