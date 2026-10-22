import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse
from django_celery_results.models import TaskResult
from testutils.factories import AsyncJobFactory, IndividualFactory, ProgramFactory

from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.utils.flex_files import write_flex_file
from country_workspace.workspaces.sites import workspace


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.mark.parametrize(
    ("url_name", "expected_admin"),
    [
        ("workspace:workspaces_countryprogram_changelist", "CountryProgramAdmin"),
        ("workspace:workspaces_countryhousehold_changelist", "CountryHouseholdAdmin"),
        ("workspace:workspaces_countryindividual_changelist", "CountryIndividualAdmin"),
        ("workspace:workspaces_countrybatch_changelist", "CountryBatchAdmin"),
        ("workspace:workspaces_countrymappingimporter_changelist", "CountryMappingImporterAdmin"),
        ("workspace:workspaces_countryrdp_changelist", "CountryRdpAdmin"),
        ("workspace:workspaces_countryasyncjob_changelist", "CountryJobAdmin"),
    ],
    ids=[
        "program",
        "household",
        "individual",
        "batch",
        "mapping_importer",
        "rdp",
        "async_job",
    ],
)
def test_current_modeladmin_for_known_changelist(rf, url_name, expected_admin):
    request = rf.get(reverse(url_name))
    assert workspace._current_modeladmin(request) == expected_admin


def test_current_modeladmin_returns_none_when_path_does_not_resolve(rf):
    """``Resolver404`` is swallowed and the function returns ``None``."""
    request = rf.get("/this/path/definitely/does/not/exist/")
    assert workspace._current_modeladmin(request) is None


def test_current_modeladmin_returns_none_for_unmapped_resolved_url(rf):
    """A URL that resolves but isn't in the lookup table returns ``None``."""
    request = rf.get(reverse("workspace:index"))
    assert workspace._current_modeladmin(request) is None


@pytest.mark.django_db
def test_flex_file_denies_a_user_without_view_permission(rf):
    """A real admin is found for the owning model, but the caller has no perm on it."""
    individual = IndividualFactory()
    reference = write_flex_file(individual, "photo", b"content", "image/png")
    flex_file_id = FlexFieldFile.parse_reference(reference)

    request = rf.get("/+ff/%s/" % flex_file_id)
    request.user = AnonymousUser()

    with pytest.raises(PermissionDenied):
        workspace.flex_file(request, str(flex_file_id))


@pytest.mark.django_db
def test_get_pending_jobs_count_no_program():
    assert workspace.get_pending_jobs_count(None) == 0


@pytest.mark.django_db
def test_get_pending_jobs_count_ignores_other_programs():
    program = ProgramFactory()
    other_program = ProgramFactory()
    AsyncJobFactory(program=other_program, curr_async_result_id="other-task-id")

    assert workspace.get_pending_jobs_count(program) == 0


@pytest.mark.django_db
def test_get_pending_jobs_count_ignores_not_queued_jobs():
    program = ProgramFactory()
    AsyncJobFactory(program=program, curr_async_result_id=None)

    assert workspace.get_pending_jobs_count(program) == 0


@pytest.mark.django_db
def test_get_pending_jobs_count_counts_queued_without_task_result():
    program = ProgramFactory()
    AsyncJobFactory(program=program, curr_async_result_id="queued-task-id")

    assert workspace.get_pending_jobs_count(program) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["PENDING", "RECEIVED", "STARTED", "RETRY"])
def test_get_pending_jobs_count_counts_active_task_result_statuses(status):
    program = ProgramFactory()
    job = AsyncJobFactory(program=program, curr_async_result_id="active-task-id")
    TaskResult.objects.create(task_id=job.curr_async_result_id, status=status)

    assert workspace.get_pending_jobs_count(program) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["SUCCESS", "FAILURE", "REVOKED"])
def test_get_pending_jobs_count_excludes_terminal_task_result_statuses(status):
    program = ProgramFactory()
    job = AsyncJobFactory(program=program, curr_async_result_id="done-task-id")
    TaskResult.objects.create(task_id=job.curr_async_result_id, status=status)

    assert workspace.get_pending_jobs_count(program) == 0
