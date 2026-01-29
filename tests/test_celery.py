import pytest

from country_workspace.config.celery import app, init_sentry
from country_workspace.tasks import removed_expired_jobs, clean_program_data
from country_workspace.models import Household, Individual, Batch, Rdp, Rdi, AsyncJob
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
    return RdpFactory.create_batch(3, program=program)


@pytest.fixture
def rdis(program):
    return [
        Rdi.objects.create(name=f"RDI {i}", program=program, hhs=[], inds=[])
        for i in range(2)
    ]


@pytest.fixture
def other_jobs(program):
    return AsyncJobFactory.create_batch(4, program=program)


@pytest.mark.django_db
def test_clean_program_data(job, batch, households, individuals):
    program = job.program

    assert Household.objects.filter(batch=batch).count() == 21
    assert Individual.objects.filter(batch=batch, removed=False).count() == 10
    assert Individual.objects.filter(batch=batch).count() == 20
    assert Batch.objects.filter(program=program).count() == 1

    result = clean_program_data(job, batch_size=5)

    assert result == {"individuals": 20, "households": 21, "batches": 1, "rdps": 0, "rdis": 0, "jobs": 0}

    assert Household.objects.filter(batch=batch).count() == 0
    assert Individual.objects.filter(batch=batch).count() == 0
    assert Batch.objects.filter(program=program).count() == 0


@pytest.mark.django_db
def test_clean_program_data_with_rdps_and_rdis(job, batch, households, individuals, rdps, rdis):
    program = job.program

    assert Household.objects.filter(batch=batch).count() == 21
    assert Individual.objects.filter(batch=batch).count() == 20
    assert Batch.objects.filter(program=program).count() == 1
    assert Rdp.objects.filter(program=program).count() == 3
    assert Rdi.objects.filter(program=program).count() == 2

    result = clean_program_data(job, batch_size=5)

    assert result == {"individuals": 20, "households": 21, "batches": 1, "rdps": 3, "rdis": 2, "jobs": 0}

    assert Household.objects.filter(batch=batch).count() == 0
    assert Individual.objects.filter(batch=batch).count() == 0
    assert Batch.objects.filter(program=program).count() == 0
    assert Rdp.objects.filter(program=program).count() == 0
    assert Rdi.objects.filter(program=program).count() == 0


@pytest.mark.django_db
def test_clean_program_data_with_jobs(job, batch, households, other_jobs):
    program = job.program

    assert AsyncJob.objects.filter(program=program).count() == 5

    result = clean_program_data(job, batch_size=5)

    assert result["jobs"] == 4
    assert AsyncJob.objects.filter(program=program).count() == 1
    assert AsyncJob.objects.filter(id=job.pk).exists()


@pytest.mark.django_db
def test_clean_program_data_multiple_batches(job):
    program = job.program
    batch1 = BatchFactory.create(program=program)
    batch2 = BatchFactory.create(program=program)

    hhs = HouseholdFactory.create_batch(5, individuals=[], batch=batch1, removed=False)
    HouseholdFactory.create_batch(5, individuals=[], batch=batch2, removed=True)
    IndividualFactory.create_batch(3, household=hhs[0], batch=batch1, removed=False)
    IndividualFactory.create_batch(3, household=hhs[0], batch=batch2, removed=True)

    assert Batch.objects.filter(program=program).count() == 2
    assert Household.objects.filter(batch__program=program).count() == 10
    assert Individual.objects.filter(batch__program=program).count() == 6

    result = clean_program_data(job, batch_size=5)

    assert result == {"individuals": 6, "households": 10, "batches": 2, "rdps": 0, "rdis": 0, "jobs": 0}

    assert Batch.objects.filter(program=program).count() == 0
    assert Household.objects.filter(batch__program=program).count() == 0
    assert Individual.objects.filter(batch__program=program).count() == 0


@pytest.mark.django_db
def test_clean_program_data_empty_program(job):
    result = clean_program_data(job)

    assert result is None


@pytest.mark.django_db
def test_clean_program_data_does_not_affect_other_programs(job, batch, households):
    other_program = ProgramFactory.create()
    other_batch = BatchFactory.create(program=other_program)
    HouseholdFactory.create_batch(5, individuals=[], batch=other_batch, removed=False)
    RdpFactory.create_batch(2, program=other_program)
    Rdi.objects.create(name="Other RDI 1", program=other_program, hhs=[], inds=[])
    Rdi.objects.create(name="Other RDI 2", program=other_program, hhs=[], inds=[])
    AsyncJobFactory.create_batch(3, program=other_program)

    result = clean_program_data(job, batch_size=5)

    assert result is not None

    assert Household.objects.filter(batch=other_batch).count() == 5
    assert Batch.objects.filter(program=other_program).count() == 1
    assert Rdp.objects.filter(program=other_program).count() == 2
    assert Rdi.objects.filter(program=other_program).count() == 2
    assert AsyncJob.objects.filter(program=other_program).count() == 3