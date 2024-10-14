from django.urls import reverse

import pytest
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from pytest_django.fixtures import SettingsWrapper
from responses import RequestsMock

from country_workspace.state import state


@pytest.fixture()
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    yield co


@pytest.fixture()
def program(office):
    from testutils.factories import ProgramFactory

    return ProgramFactory()


@pytest.fixture()
def user():
    from testutils.factories import UserFactory

    return UserFactory(is_staff=True)


@pytest.fixture()
def data(program):
    from testutils.factories import HouseholdFactory

    return HouseholdFactory.create_batch(10, batch__program=program, batch__country_office=program.country_office)


@pytest.fixture()
def app(
    django_app_factory: "MixinWithInstanceVariables",
    mocked_responses: "RequestsMock",
    settings: SettingsWrapper,
) -> "DjangoTestApp":
    settings.FLAGS = {"OLD_STYLE_UI": [("boolean", True)]}
    django_app = django_app_factory(csrf_checks=False)
    state.reset()
    yield django_app


def test_login(app, user, program, data):
    from testutils.perms import user_grant_permissions, user_grant_role

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
    assert "Seems you do not have any tenant enabled." in res.text

    with user_grant_role(user, program.country_office):
        res = app.get(reverse("workspace:select_tenant"), user=user)
        res.forms["select-tenant"]["tenant"] = program.country_office.pk
        res = res.forms["select-tenant"].submit()
        assert app.cookies["selected_tenant"] == program.country_office.slug
        res = res.follow()
        assert "You don't have permission to view anything here." in res.text

    with user_grant_permissions(
        user,
        [
            "workspaces.view_countryhousehold",
            "workspaces.view_countryindividual",
        ],
        program.country_office,
    ):
        hh = program.country_office.programs.first().households.first()
        res = app.get(reverse("workspace:select_tenant"), user=user)
        res.forms["select-tenant"]["tenant"] = program.country_office.pk
        res = res.forms["select-tenant"].submit()
        assert app.cookies["selected_tenant"] == program.country_office.slug
        res = res.follow()
        res = res.click("Country Households")
        assert "Please select a program on the left" in res.text
        base_url = reverse("workspace:workspaces_countryhousehold_changelist")
        res = app.get(f"{base_url}?batch__program__exact={hh.program.id}", user=user)
        res = res.click(hh.name)
        res = res.click("Close", verbose=True)

        # res = res.pyquery('a.closelink')[0].click()
