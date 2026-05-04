from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.urls import reverse
from strategy_field.utils import fqn

from country_workspace.admin.sync_log import sync_flex_fields_task
from country_workspace.models import AsyncJob, SyncLog

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from country_workspace.models import User


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


def test_sync_flex_fields_creates_async_job(app: "CWTestApp"):
    url = reverse("admin:country_workspace_synclog_sync_flex_fields")
    response = app.get(url)

    assert response.status_code == 302
    job = AsyncJob.objects.latest("pk")
    assert job.description == "Sync Flex Fields"
    assert job.type == AsyncJob.JobType.TASK
    assert job.action == fqn(sync_flex_fields_task)
    assert job.program is None


def test_sync_flex_fields_task_calls_refresh():
    with patch.object(SyncLog.objects, "refresh") as mock_refresh:
        sync_flex_fields_task(job=None)
        mock_refresh.assert_called_once()
