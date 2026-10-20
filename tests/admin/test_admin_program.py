from typing import TYPE_CHECKING

import pytest
from constance.test import override_config
from django.urls import reverse
from pytest_mock import MockerFixture
from strategy_field.utils import fqn

from country_workspace.models import AsyncJob, Rdp
from country_workspace.tasks import clean_program_data

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryProgram


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def push_pending_rdp(program: "CountryProgram") -> Rdp:
    from testutils.factories import RdpFactory

    rdp = RdpFactory(program=program)
    rdp.start_push_attempt()
    return rdp


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    admin_user: "User",
) -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.parametrize("dedup_configured", [False, True])
def test_program_clean_program(
    app: "CWTestApp",
    program: "CountryProgram",
    admin_user: "User",
    mocker: MockerFixture,
    django_capture_on_commit_callbacks: "DjangoCaptureOnCommitCallbacks",
    dedup_configured: bool,
) -> None:
    queue = mocker.patch.object(AsyncJob, "queue", autospec=True, return_value=None)
    base_url = reverse("admin:country_workspace_program_clean_program", args=[program.pk])

    with override_config(
        DEDUP_API_URL="https://dedup.example.org" if dedup_configured else "",
        DEDUP_API_TOKEN="token" if dedup_configured else "",
    ):
        res = app.get(base_url, expect_errors=True)
        with django_capture_on_commit_callbacks(execute=True):
            res = res.forms[1].submit()
            job = AsyncJob.objects.get(program=program)
            queue.assert_not_called()

        program.refresh_from_db()
        assert program.cleanup_in_progress is True
        assert job.owner_id == admin_user.pk
        assert job.type == AsyncJob.JobType.TASK
        assert job.action == fqn(clean_program_data)
        assert job.repeatable is True
        assert job.config == {
            "deduplication_set_group_reference_id": program.unicef_id if dedup_configured else None,
        }
        queue.assert_called_once_with(job)

        with django_capture_on_commit_callbacks(execute=True):
            res = app.post(base_url)

        assert AsyncJob.objects.get(program=program).pk == job.pk
        queue.assert_called_once_with(job)

    assert "already in progress" in res.follow().text


def test_program_clean_program_rejects_pending_push(
    app: "CWTestApp",
    program: "CountryProgram",
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    queue = mocker.patch.object(AsyncJob, "queue", autospec=True, return_value=None)
    base_url = reverse("admin:country_workspace_program_clean_program", args=[program.pk])

    res = app.post(base_url)

    program.refresh_from_db()
    push_pending_rdp.refresh_from_db()
    assert program.cleanup_in_progress is False
    assert not AsyncJob.objects.filter(program=program).exists()
    assert push_pending_rdp.status == Rdp.PushStatus.PUSH_PENDING
    queue.assert_not_called()
    assert "push is pending" in res.follow().text


def test_program_clean_program_rolls_back_when_job_creation_fails(
    app: "CWTestApp",
    program: "CountryProgram",
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(AsyncJob.objects, "create", side_effect=RuntimeError("job creation failed"))
    base_url = reverse("admin:country_workspace_program_clean_program", args=[program.pk])

    res = app.post(base_url)

    assert res.status_code == 302
    program.refresh_from_db()
    assert program.cleanup_in_progress is False
    assert not AsyncJob.objects.filter(program=program).exists()
