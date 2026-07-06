from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import Rdp, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    app = django_app_factory(csrf_checks=False)
    app.set_user(admin_user)
    return app


@pytest.fixture
def rdp() -> "Rdp":
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory()


def test_rdp_changelist(app: "CWTestApp") -> None:
    assert app.get(reverse("admin:country_workspace_rdp_changelist")).status_code == 200


def test_rdp_change_view(app: "CWTestApp", rdp: "Rdp") -> None:
    assert app.get(reverse("admin:country_workspace_rdp_change", args=[rdp.pk])).status_code == 200


def test_rdp_add_forbidden(app: "CWTestApp") -> None:
    assert app.get(reverse("admin:country_workspace_rdp_add"), expect_errors=True).status_code == 403


def test_rdp_related_job_link(app: "CWTestApp", rdp: "Rdp") -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(rdp=rdp, program=rdp.program)
    res = app.get(reverse("admin:country_workspace_rdp_change", args=[rdp.pk]))
    assert reverse("admin:country_workspace_asyncjob_change", args=[job.pk]) in res.text


def test_rdp_view_in_workspace_link(app: "CWTestApp", rdp: "Rdp") -> None:
    url = reverse("admin:country_workspace_rdp_changelist")
    workspace_url = reverse("workspace:workspaces_countryrdp_changelist")
    res = app.get(f"{url}?program={rdp.program.pk}")
    assert f"{workspace_url}?program={rdp.program.pk}" in res.text
