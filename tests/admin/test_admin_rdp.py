from typing import TYPE_CHECKING

import pytest
from django.contrib import admin
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.admin.rdp import RdpAdmin
from country_workspace.workspaces.models import CountryRdp

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import Rdp


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(country_office=office)


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def parent_rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def child_rdp(parent_rdp):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(
        program=parent_rdp.program,
        pushed_by=parent_rdp.pushed_by,
        parent=parent_rdp,
    )


@pytest.fixture(params=[True, False])
def job(request, rdp):
    from testutils.factories import AsyncJobFactory

    if request.param:
        return AsyncJobFactory(rdp=rdp, program=rdp.program)
    return None


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.parametrize(
    ("view_type", "args", "params"),
    [
        ("changelist", [], ""),
        ("changelist", [], "?program={}"),
        ("change", ["{}"], ""),
        ("add", [], ""),
    ],
    ids=["changelist", "changelist_filtered", "change_view", "add_forbidden"],
)
def test_rdp_views(app, rdp: "Rdp", view_type, args, params):
    url_name = f"admin:country_workspace_rdp_{view_type}"
    formatted_args = [arg.format(rdp.pk) if arg else None for arg in args if arg]
    formatted_params = params.format(rdp.program.pk) if "{}" in params else params

    base_url = reverse(url_name, args=formatted_args)

    if view_type == "add":
        res = app.get(base_url, expect_errors=True)
        assert res.status_code == 403
    else:
        res = app.get(f"{base_url}{formatted_params}")
        assert res.status_code == 200


@pytest.mark.parametrize(
    "button_type",
    [
        "records",
        "view_in_workspace",
        "related_job",
    ],
    ids=["records_button", "workspace_button", "related_job_link"],
)
def test_rdp_buttons_and_links(app, rdp: "Rdp", button_type, job):
    if button_type == "view_in_workspace":
        base_url = reverse("admin:country_workspace_rdp_changelist")
        res = app.get(f"{base_url}?program={rdp.program.pk}")
    else:
        base_url = reverse("admin:country_workspace_rdp_change", args=[rdp.pk])
        res = app.get(base_url)

    assert res.status_code == 200

    if button_type == "related_job" and job:
        job = rdp.jobs.first()
        job_url = reverse("admin:country_workspace_asyncjob_change", args=[job.pk])
        assert job_url in res.text


@pytest.mark.django_db
def test_records_link_uses_parent_selection_owner(
    mocker: MockerFixture,
    parent_rdp: "Rdp",
    child_rdp: "Rdp",
) -> None:
    parent_rdp.program.beneficiary_group.master_detail = True
    parent_rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    button = mocker.MagicMock(context={"original": child_rdp})

    RdpAdmin(CountryRdp, admin.site).records(button)

    assert button.href.endswith(f"?rdp__exact={parent_rdp.pk}")
