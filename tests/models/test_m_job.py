import pytest
from unittest.mock import Mock, patch, PropertyMock

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


def test_job_info_no_result(program):
    job = AsyncJobFactory(program=program)
    assert job.info == "-"


@patch("country_workspace.models.AsyncJob.async_result", new_callable=PropertyMock)
def test_job_info_with_result(mock_async_result, program):
    job = AsyncJobFactory(program=program)
    mock_async_result.return_value = Mock(result={"status": "completed", "count": 5})
    assert job.info == "status: completed\ncount: 5\n"


@patch("country_workspace.models.AsyncJob.async_result", new_callable=PropertyMock)
def test_job_info_with_exception(mock_async_result, program):
    job = AsyncJobFactory(program=program)
    mock_async_result.return_value = Mock(result=Exception("boom"))
    assert job.info == "-"
