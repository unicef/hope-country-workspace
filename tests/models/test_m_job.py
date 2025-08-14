import pytest

from testutils.factories import AsyncJobFactory, ProgramFactory


@pytest.fixture
def program():
    return ProgramFactory()


def test_job_create_new(program):
    action = "test_action"
    description = "test_description"
    job_1 = AsyncJobFactory(program=program, description=description, action=action)
    job_2 = AsyncJobFactory(program=program, description=description, action=action)

    assert job_1.description == f"{description} #1"
    assert job_2.description == f"{description} #2"


def test_job_save_existing(program):
    action = "test_action"
    description = "test_description"
    job_1 = AsyncJobFactory(program=program, description=description, action=action)
    job_1.save()
    assert job_1.description == f"{description} #1"
