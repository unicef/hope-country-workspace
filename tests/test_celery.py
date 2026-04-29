import pytest
from unittest.mock import patch, PropertyMock

from celery.exceptions import Ignore

from country_workspace.cache.manager import cache_manager
from country_workspace.config.celery import app, init_sentry
from country_workspace.models import Household, Individual, Batch, Rdp, Rdi, AsyncJob
from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.tasks import (
    SYNC_HOPE_DATA_PERIODIC_TASK_NAME,
    clean_program_data,
    removed_expired_jobs,
    sync_hope_data,
    sync_job_task,
)
from tests.extras.testutils.factories import (
    ProgramFactory,
    BatchFactory,
    HouseholdFactory,
    IndividualFactory,
    AsyncJobFactory,
    RdpFactory,
)


def test_celery_app(**kwargs):
    app.autodiscover_tasks()
    assert True


def test_celery_init_sentry(**kwargs):
    init_sentry()
    assert True


def test_removed_expired_jobs(**kwargs):
    removed_expired_jobs()


@pytest.fixture
def program():
    return ProgramFactory.create()


@pytest.fixture
def batch(program):
    return BatchFactory.create(program=program)


@pytest.fixture
def job(program):
    return AsyncJobFactory.create(program=program)


@pytest.fixture
def households(batch):
    HouseholdFactory.create_batch(10, individuals=[], batch=batch, errors={}, removed=False)
    HouseholdFactory.create_batch(10, individuals=[], batch=batch, removed=True)


@pytest.fixture
def individuals(batch):
    hh = HouseholdFactory.create(batch=batch, individuals=[])
    IndividualFactory.create_batch(10, household=hh, errors={}, removed=False)
    IndividualFactory.create_batch(10, household=hh, removed=True)


@pytest.fixture
def rdps(program):
    return [
        RdpFactory.create(program=program, status=Rdp.PushStatus.PENDING),
        RdpFactory.create(program=program, status=Rdp.PushStatus.SUCCESS),
        RdpFactory.create(program=program, status=Rdp.PushStatus.FAILURE),
    ]


@pytest.fixture
def rdis(program):
    return [Rdi.objects.create(name=f"RDI {i}", program=program, hhs=[], inds=[]) for i in range(2)]


@pytest.fixture
def other_jobs(program):
    return AsyncJobFactory.create_batch(4, program=program)


@pytest.mark.django_db
def test_clean_program_data(job, batch, households, individuals):
    program = job.program

    initial_households = Household.objects.filter(batch__program=program).count()
    initial_individuals = Individual.objects.filter(batch__program=program).count()

    assert initial_households > 0
    assert initial_individuals > 0
    assert Batch.objects.filter(program=program).count() > 0

    result = clean_program_data(job, batch_size=5)

    assert result is not None
    assert result["batches"] > 0
    assert result["households"] == initial_households
    assert result["individuals"] == initial_individuals

    assert Household.objects.filter(batch__program=program).count() == 0
    assert Individual.objects.filter(batch__program=program).count() == 0
    assert Batch.objects.filter(program=program).count() == 0


@pytest.mark.django_db
def test_clean_program_data_with_rdps_and_rdis(job, batch, households, individuals, rdps, rdis):
    program = job.program

    assert Batch.objects.filter(program=program).count() > 0
    assert Rdp.objects.filter(program=program).count() == 3
    assert Rdi.objects.filter(program=program).count() == 2

    result = clean_program_data(job, batch_size=5)

    assert result is not None
    assert result["batches"] > 0
    assert result["households"] > 0
    assert result["individuals"] > 0
    assert result["rdps"] == 3
    assert result["rdis"] == 2

    assert Batch.objects.filter(program=program).count() == 0
    assert Rdp.objects.filter(program=program).count() == 0
    assert Rdi.objects.filter(program=program).count() == 0


@pytest.mark.django_db
def test_clean_program_data_with_jobs(job, batch, households, other_jobs):
    program = job.program

    assert AsyncJob.objects.filter(program=program).count() == 5

    result = clean_program_data(job, batch_size=5)

    assert result["jobs"] == 4
    assert result["households"] > 0
    assert AsyncJob.objects.filter(program=program).count() == 1
    assert AsyncJob.objects.filter(id=job.pk).exists()


@pytest.mark.django_db
def test_clean_program_data_multiple_batches(job):
    program = job.program
    batch1 = BatchFactory.create(program=program)
    batch2 = BatchFactory.create(program=program)

    HouseholdFactory.create_batch(5, individuals=[], batch=batch1, removed=False)
    HouseholdFactory.create_batch(5, individuals=[], batch=batch2, removed=True)

    initial_households = Household.objects.filter(batch__program=program).count()

    assert Batch.objects.filter(program=program).count() >= 2
    assert initial_households >= 10

    result = clean_program_data(job, batch_size=1)

    assert result is not None
    assert result["batches"] >= 2
    assert result["households"] == initial_households

    assert Batch.objects.filter(program=program).count() == 0
    assert Household.objects.filter(batch__program=program).count() == 0


@pytest.mark.django_db
def test_clean_program_data_does_not_affect_other_programs(job, batch, households):
    other_program = ProgramFactory.create()
    other_batch = BatchFactory.create(program=other_program)
    HouseholdFactory.create_batch(5, individuals=[], batch=other_batch, removed=False)
    RdpFactory.create(program=other_program, status=Rdp.PushStatus.SUCCESS)
    RdpFactory.create(program=other_program, status=Rdp.PushStatus.FAILURE)
    Rdi.objects.create(name="Other RDI 1", program=other_program, hhs=[], inds=[])
    Rdi.objects.create(name="Other RDI 2", program=other_program, hhs=[], inds=[])
    AsyncJobFactory.create_batch(3, program=other_program)

    other_program_batch_count = Batch.objects.filter(program=other_program).count()
    other_program_household_count = Household.objects.filter(batch__program=other_program).count()

    result = clean_program_data(job, batch_size=5)

    assert result is not None
    assert Household.objects.filter(batch__program=other_program).count() == other_program_household_count
    assert Batch.objects.filter(program=other_program).count() == other_program_batch_count
    assert Rdp.objects.filter(program=other_program).count() == 2
    assert Rdi.objects.filter(program=other_program).count() == 2
    assert AsyncJob.objects.filter(program=other_program).count() == 3


@pytest.mark.django_db
def test_clean_program_data_stops_when_cancellation_requested(job, batch, households):
    initial_batches = Batch.objects.filter(program=job.program).count()

    with patch(
        "country_workspace.models.AsyncJob.is_termination_requested",
        new_callable=PropertyMock,
    ) as requested:
        requested.return_value = True
        with pytest.raises(GracefulJobCancellationError):
            clean_program_data(job, batch_size=1)

    assert Batch.objects.filter(program=job.program).count() == initial_batches


@pytest.mark.django_db
def test_clean_program_data_bumps_cache_version_exactly_once(job, batch, households, individuals):
    program = job.program
    version_before = cache_manager.get_cache_version(program=program)

    result = clean_program_data(job, batch_size=5)

    assert result is not None
    assert result["households"] > 0
    assert result["individuals"] > 0

    version_after = cache_manager.get_cache_version(program=program)
    assert version_after == version_before + 1, (
        "cache version must be bumped exactly once: per-row post_save/post_delete "
        "updates are suppressed during the bulk delete and a single bump is issued "
        "at the end"
    )


@pytest.mark.django_db
def test_sync_job_task_handles_graceful_cancellation(mocker, job):
    initial_batches = Batch.objects.filter(program=job.program).count()

    mocker.patch.object(AsyncJob, "ensure_not_cancelled")
    mocker.patch.object(AsyncJob, "execute", side_effect=GracefulJobCancellationError("cancel requested"))
    cancel_mock = mocker.patch.object(AsyncJob, "cancel")
    update_state_mock = mocker.patch.object(sync_job_task, "update_state")

    with pytest.raises(Ignore):
        sync_job_task.run(job.pk, job.version)

    cancel_mock.assert_called_once()
    update_state_mock.assert_called_once_with(
        state="REVOKED",
        meta={
            "exc_type": "GracefulJobCancellationError",
            "exc_module": "country_workspace.models.jobs",
            "exc_message": "cancel requested",
        },
    )

    assert Batch.objects.filter(program=job.program).count() == initial_batches


@pytest.mark.django_db
def test_sync_job_task_cancels_when_ensure_not_cancelled_raises(mocker, job):
    reason = "cancel requested"
    ensure_not_cancelled_mock = mocker.patch.object(
        AsyncJob,
        "ensure_not_cancelled",
        side_effect=GracefulJobCancellationError(reason),
    )
    execute_mock = mocker.patch.object(AsyncJob, "execute")
    cancel_mock = mocker.patch.object(AsyncJob, "cancel")
    update_state_mock = mocker.patch.object(sync_job_task, "update_state")

    with pytest.raises(Ignore):
        sync_job_task.run(job.pk, job.version)

    ensure_not_cancelled_mock.assert_called_once_with(refresh=True)
    execute_mock.assert_not_called()
    cancel_mock.assert_called_once()
    update_state_mock.assert_called_once_with(
        state="REVOKED",
        meta={
            "exc_type": "GracefulJobCancellationError",
            "exc_module": "country_workspace.models.jobs",
            "exc_message": reason,
        },
    )


@pytest.mark.django_db
def test_sync_hope_data_runs_delta_and_flex_fields(mocker):
    program_runner = mocker.patch("country_workspace.tasks.run_program_sync")
    geo_runner = mocker.patch("country_workspace.tasks.run_geo_sync")
    flex_runner = mocker.patch("country_workspace.tasks.run_flex_fields_sync")

    result = sync_hope_data.run()

    program_runner.assert_called_once_with(delta_sync=True)
    geo_runner.assert_called_once_with(delta_sync=True)
    flex_runner.assert_called_once_with()
    assert result == {"programs": True, "geo": True, "flex_fields": True}


@pytest.mark.django_db
def test_sync_hope_data_isolates_failures(mocker):
    mocker.patch("country_workspace.tasks.run_program_sync", side_effect=RuntimeError("boom"))
    geo_runner = mocker.patch("country_workspace.tasks.run_geo_sync")
    flex_runner = mocker.patch("country_workspace.tasks.run_flex_fields_sync")
    capture = mocker.patch("country_workspace.tasks.sentry_sdk.capture_exception")

    result = sync_hope_data.run()

    geo_runner.assert_called_once_with(delta_sync=True)
    flex_runner.assert_called_once_with()
    capture.assert_called_once()
    assert result == {"programs": False, "geo": True, "flex_fields": True}


@pytest.mark.django_db
def test_register_hope_sync_periodic_task_script_is_idempotent():
    import importlib.util
    from pathlib import Path

    from django.core.management import call_command
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    call_command("upgradescripts", ["apply"])
    call_command("upgradescripts", ["apply"])

    task = PeriodicTask.objects.get(name=SYNC_HOPE_DATA_PERIODIC_TASK_NAME)
    assert task.task == "country_workspace.tasks.sync_hope_data"
    assert task.queue == "queue_hcw"
    assert task.enabled is True
    assert task.interval is not None
    assert task.interval.every == 1
    assert task.interval.period == IntervalSchedule.HOURS

    script_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "country_workspace"
        / "versioning"
        / "scripts"
        / "0033_register_hope_sync_periodic_task.py"
    )
    spec = importlib.util.spec_from_file_location("_hcw_periodic_sync_script", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.backward()
    assert not PeriodicTask.objects.filter(name=SYNC_HOPE_DATA_PERIODIC_TASK_NAME).exists()
