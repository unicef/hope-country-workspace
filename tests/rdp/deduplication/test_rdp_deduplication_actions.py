from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.deduplication import actions
from country_workspace.rdp.deduplication.types import DeduplicationLogAction


def test_approve_without_operation_is_noop(mocker: MockerFixture) -> None:
    make_client = mocker.patch.object(actions, "make_dedup_client")
    append_log = mocker.patch.object(actions, "append_rdp_operation_log")

    actions.approve_deduplication_set_after_successful_push(
        operation_id=None,
        group_reference_id="PROGRAM",
    )

    make_client.assert_not_called()
    append_log.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [None, RemoteError("remote"), RemoteUnavailableError("unavailable")],
    ids=["success", "remote_error", "unavailable"],
)
def test_approve_deduplication_set(
    mocker: MockerFixture,
    error: Exception | None,
) -> None:
    operation_id = uuid4()
    make_client = mocker.patch.object(actions, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    append_log = mocker.patch.object(actions, "append_rdp_operation_log")
    if error:
        client.approve.side_effect = error

    actions.approve_deduplication_set_after_successful_push(
        operation_id=operation_id,
        group_reference_id="PROGRAM",
    )

    make_client.assert_called_once_with("PROGRAM", deduplication_set_id=str(operation_id))
    client.approve.assert_called_once_with()
    assert append_log.call_args.kwargs["action"] == DeduplicationLogAction.APPROVE_SET
    assert append_log.call_args.kwargs["result"]["success"] is (error is None)
    assert append_log.call_args.kwargs["operation_id"] == operation_id
    if error:
        assert str(error) in append_log.call_args.kwargs["result"]["error"]


@pytest.mark.parametrize(
    "error",
    [None, RemoteError("remote"), RemoteUnavailableError("unavailable")],
    ids=["success", "remote_error", "unavailable"],
)
def test_reject_deduplication_set(
    mocker: MockerFixture,
    error: Exception | None,
) -> None:
    operation_id = uuid4()
    make_client = mocker.patch.object(actions, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    append_log = mocker.patch.object(actions, "append_rdp_operation_log")
    if error:
        client.reject.side_effect = error

    if error:
        with pytest.raises(type(error)):
            actions.reject_deduplication_set(operation_id=operation_id, group_reference_id="PROGRAM")
    else:
        actions.reject_deduplication_set(operation_id=operation_id, group_reference_id="PROGRAM")

    assert append_log.call_args.kwargs["action"] == DeduplicationLogAction.REJECT_SET
    assert append_log.call_args.kwargs["result"]["success"] is (error is None)
    make_client.assert_called_once_with("PROGRAM", deduplication_set_id=str(operation_id))
    client.reject.assert_called_once_with()
