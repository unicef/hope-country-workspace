import pytest
from unittest.mock import Mock, patch, PropertyMock

from testutils.factories import AsyncJobFactory, BatchFactory, ProgramFactory
from country_workspace.models.jobs import GracefulJobCancellationError


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


@pytest.mark.django_db
def test_job_save_sets_group_key_for_batch() -> None:
    batch = BatchFactory()
    job = AsyncJobFactory(batch=batch, program=batch.program, group_key=None)

    assert job.group_key == f"batch:{batch.pk}"


@pytest.mark.django_db
def test_job_save_keeps_existing_group_key_for_batch() -> None:
    batch = BatchFactory()
    job = AsyncJobFactory(batch=batch, program=batch.program, group_key="custom-key")

    assert job.group_key == "custom-key"


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


@pytest.mark.django_db
def test_request_cancellation_sets_tracking_flag(program):
    job = AsyncJobFactory(program=program)
    job.curr_async_result_id = "task-id-123"

    with patch.object(job, "set_tracking_info") as set_tracking_info:
        result = job.request_cancellation()

    assert result is True
    set_tracking_info.assert_called_once_with("terminate_requested", "1")


@pytest.mark.django_db
def test_request_cancellation_returns_false_without_task_id(program):
    job = AsyncJobFactory(program=program)
    assert job.request_cancellation() is False


@pytest.mark.django_db
def test_ensure_not_cancelled_raises_when_termination_requested(program):
    job = AsyncJobFactory(program=program)

    with patch("country_workspace.models.AsyncJob.is_termination_requested", new_callable=PropertyMock) as requested:
        requested.return_value = True
        with pytest.raises(GracefulJobCancellationError):
            job.ensure_not_cancelled()
