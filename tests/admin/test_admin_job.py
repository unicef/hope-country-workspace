from typing import TYPE_CHECKING

import pytest
from django.contrib.admin.sites import AdminSite
from django.urls import reverse
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import AsyncJob


@pytest.fixture
def job():
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory()


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


def test_job_filtering(app, job: "AsyncJob"):
    base_url = reverse("admin:country_workspace_asyncjob_changelist")
    app.get(base_url)

    app.get(f"{base_url}?program={job.program.pk}")
    app.get(f"{base_url}?program={job.program.pk}&failed=f")
    app.get(f"{base_url}?program={job.program.pk}&failed=s")
    app.get(f"{base_url}?program={job.program.pk}&failed=x")


@pytest.mark.django_db
def test_get_readonly_fields_superuser_includes_result(rf, job, admin_site):
    from country_workspace.admin.job import AsyncJobAdmin

    admin = AsyncJobAdmin(model=job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock(is_superuser=True)

    fields = admin.get_readonly_fields(request, job)
    assert "error" in fields
    assert "result" in fields


@pytest.mark.django_db
def test_get_readonly_fields_non_superuser_excludes_result(rf, job, admin_site):
    from country_workspace.admin.job import AsyncJobAdmin

    admin = AsyncJobAdmin(model=job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock(is_superuser=False)

    fields = admin.get_readonly_fields(request, job)
    assert "error" in fields
    assert "result" not in fields
