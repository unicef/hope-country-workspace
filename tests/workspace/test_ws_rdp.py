from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.workspaces.models import CountryRdp

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def rdp() -> "CountryRdp":
    from testutils.factories import CountryProgramFactory, CountryRdpFactory, OfficeFactory

    office = OfficeFactory()
    state.tenant = office
    return CountryRdpFactory(program=CountryProgramFactory(country_office=office))


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "CWTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_rdp_change_heading(app: "CWTestApp", rdp: "CountryRdp") -> None:
    url = reverse("workspace:workspaces_countryrdp_change", args=[rdp.pk])
    with select_office(app, rdp.program.country_office, rdp.program):
        res = app.get(url)
    assert res.status_code == 200

    heading = res.pyquery(".title-top .page-heading")
    assert heading.find(".page-breadcrumbs li").text() == "Rdps"
    assert heading.find("h2").text() == str(rdp)
    assert not heading.find(".status-box")
    assert res.pyquery(".title-top .title-actions .status-box").text() == rdp.get_status_display()
