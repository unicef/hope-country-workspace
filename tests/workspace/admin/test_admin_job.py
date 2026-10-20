from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from django.contrib.admin.sites import AdminSite
from django.urls import reverse
from django.utils import timezone
from pytest_mock import MockerFixture
from strategy_field.utils import fqn
from testutils.factories import AsyncJobFactory, ProgramFactory

from country_workspace.tasks import clean_program_data


@pytest.fixture
def async_job():
    return AsyncJobFactory()


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.mark.django_db
def test_job_status(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)

    expected_status = "PENDING"
    with patch("country_workspace.models.AsyncJob.task_status", new_callable=PropertyMock) as mock_status:
        mock_status.return_value = expected_status
        assert admin.status(async_job) == expected_status


@pytest.mark.django_db
def test_job_completed_time(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)

    completed_time = timezone.now().isoformat()
    with patch("country_workspace.models.AsyncJob.task_info", new_callable=PropertyMock) as mock_info:
        mock_info.return_value = {"completed_at": completed_time}
        assert admin.completed_time(async_job) == completed_time

    with patch("country_workspace.models.AsyncJob.task_info", new_callable=PropertyMock) as mock_info:
        mock_info.return_value = {}
        assert admin.completed_time(async_job) == "Pending"

    with patch("country_workspace.models.AsyncJob.task_info", new_callable=PropertyMock) as mock_info:
        mock_info.side_effect = AttributeError()
        assert admin.completed_time(async_job) == "Pending"


@pytest.mark.django_db
def test_celery_check(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get(reverse("workspace:workspaces_countryasyncjob_changelist"))

    request.user = MagicMock()
    request.user.has_perm.return_value = True

    def mock_get_object(request, object_id):
        return async_job

    admin.get_object = mock_get_object

    check_called = False

    def mock_check():
        nonlocal check_called
        check_called = True

    async_job.check = mock_check

    handler = admin.celery_check

    handler.func(admin, request, str(async_job.pk))
    assert check_called, "The check method should have been called"


@pytest.mark.django_db
def test_celery_cancel_action_available(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    assert hasattr(admin, "celery_cancel")


@pytest.mark.django_db
def test_has_add_permission(rf, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=AsyncJobFactory._meta.model, admin_site=admin_site)
    request = rf.get("/")

    assert not admin.has_add_permission(request), "Should not have add permission"


@pytest.mark.django_db
def test_has_delete_permission(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get("/")

    assert not admin.has_delete_permission(request), "Should not have delete permission without object"

    assert not admin.has_delete_permission(request, async_job), "Should not have delete permission with object"


@pytest.mark.django_db
def test_get_form_sets_description_width(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock()

    form = admin.get_form(request, async_job)

    assert "description" in form.base_fields
    assert form.base_fields["description"].widget.attrs.get("style") == "width: 800px;"


@pytest.mark.django_db
def test_get_form_sets_description_width_without_obj(rf, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin
    from country_workspace.workspaces.models import CountryAsyncJob

    admin = CountryJobAdmin(model=CountryAsyncJob, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock()

    form = admin.get_form(request, None)

    assert "description" in form.base_fields
    assert form.base_fields["description"].widget.attrs.get("style") == "width: 800px;"


@pytest.mark.django_db
def test_get_fields_superuser_includes_result(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock(is_superuser=True)

    assert admin.get_fields(request, async_job) == ("description", "error", "result")


@pytest.mark.django_db
def test_get_fields_non_superuser_excludes_result(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock(is_superuser=False)

    assert admin.get_fields(request, async_job) == ("description", "error")


@pytest.mark.django_db
def test_get_readonly_fields_superuser_includes_result(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock(is_superuser=True)

    assert admin.get_readonly_fields(request, async_job) == ("error", "result")


@pytest.mark.django_db
def test_get_readonly_fields_non_superuser_excludes_result(rf, async_job, admin_site):
    from country_workspace.workspaces.admin.job import CountryJobAdmin

    admin = CountryJobAdmin(model=async_job.__class__, admin_site=admin_site)
    request = rf.get("/")
    request.user = MagicMock(is_superuser=False)

    assert admin.get_readonly_fields(request, async_job) == ("error",)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("cleanup_job", "cleanup_in_progress", "allowed"),
    [
        (False, False, True),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_has_queue_permission_during_program_cleanup(
    rf,
    admin_site,
    mocker: MockerFixture,
    cleanup_job: bool,
    cleanup_in_progress: bool,
    allowed: bool,
) -> None:
    from country_workspace.workspaces.admin import job as job_admin
    from country_workspace.workspaces.models import CountryAsyncJob

    program = ProgramFactory(cleanup_in_progress=cleanup_in_progress)
    job = AsyncJobFactory(
        program=program,
        action=fqn(clean_program_data) if cleanup_job else "other.job",
    )
    job = CountryAsyncJob.objects.get(pk=job.pk)
    admin = job_admin.CountryJobAdmin(model=CountryAsyncJob, admin_site=admin_site)
    request = rf.get("/")
    mocker.patch.object(job_admin, "can_debug_async_job", return_value=True)

    assert admin.has_queue_permission("queue", request, job) is allowed
