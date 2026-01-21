import pytest

from country_workspace.config.celery import app, init_sentry
from country_workspace.tasks import removed_expired_jobs, clean_program_data
from tests.extras.testutils.factories import (
    ProgramFactory,
    BatchFactory,
    HouseholdFactory,
    IndividualFactory,
    AsyncJobFactory,
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
def households(program, batch):
    HouseholdFactory.create_batch(10, individuals=[], batch=batch, errors={}, removed=False)
    HouseholdFactory.create_batch(10, individuals=[], batch=batch, removed=True)


@pytest.fixture
def individuals(program, batch):
    hh = HouseholdFactory.create(batch=batch, individuals=[])
    IndividualFactory.create_batch(10, household=hh, errors={}, removed=False)
    IndividualFactory.create_batch(10, household=hh, removed=True)


@pytest.mark.django_db
def test_clean_program_data(job, batch, households, individuals):
    assert HouseholdFactory._meta.model.objects.filter(batch=batch).count() == 21
    assert IndividualFactory._meta.model.objects.filter(batch=batch, removed=False).count() == 10
    assert IndividualFactory._meta.model.objects.filter(batch=batch).count() == 20

    result = clean_program_data(job, batch_size=5)

    assert result == {"individuals": 10, "households": 11}

    assert HouseholdFactory._meta.model.objects.filter(batch=batch).count() == 10
    assert IndividualFactory._meta.model.objects.filter(batch=batch).count() == 0


@pytest.mark.django_db
def test_clean_program_data_empty_program(job):
    result = clean_program_data(job)

    assert result is None
