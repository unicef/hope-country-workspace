from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.biographic import actions
from country_workspace.rdp.deduplication.types import DeduplicationLogAction

pytestmark = pytest.mark.django_db


def test_approve_without_operation_is_noop(mocker: MockerFixture) -> None:
    make_client = mocker.patch.object(actions, "make_biographic_client")

    actions.approve_biographic_set_after_successful_push(operation_id=None)

    make_client.assert_not_called()


def test_approve_without_external_id_is_noop(biographic_operation, mocker: MockerFixture) -> None:
    biographic_operation.external_id = ""
    biographic_operation.save()
    make_client = mocker.patch.object(actions, "make_biographic_client")
    append_log = mocker.patch.object(actions, "append_rdp_operation_log")

    actions.approve_biographic_set_after_successful_push(operation_id=biographic_operation.id)

    make_client.assert_not_called()
    append_log.assert_not_called()


@pytest.mark.parametrize("error", [None, RemoteError("remote"), RemoteUnavailableError("unavailable")])
def test_approve_biographic_set(biographic_operation, mocker: MockerFixture, error: Exception | None) -> None:
    make_client = mocker.patch.object(actions, "make_biographic_client")
    client = make_client.return_value.__enter__.return_value
    append_log = mocker.patch.object(actions, "append_rdp_operation_log")
    if error:
        client.approve.side_effect = error

    actions.approve_biographic_set_after_successful_push(operation_id=biographic_operation.id)

    make_client.assert_called_once_with(biographic_operation.rdp.program, dataset_id="7")
    client.approve.assert_called_once_with()
    assert append_log.call_args.kwargs["action"] == DeduplicationLogAction.APPROVE_SET
    assert append_log.call_args.kwargs["result"]["success"] is (error is None)
    if error:
        assert str(error) in append_log.call_args.kwargs["result"]["error"]


@pytest.mark.parametrize("error", [None, RemoteError("remote"), RemoteUnavailableError("unavailable")])
def test_reject_biographic_set(biographic_operation, mocker: MockerFixture, error: Exception | None) -> None:
    make_client = mocker.patch.object(actions, "make_biographic_client")
    client = make_client.return_value.__enter__.return_value
    append_log = mocker.patch.object(actions, "append_rdp_operation_log")
    if error:
        client.reject.side_effect = error

    if error:
        with pytest.raises(type(error)):
            actions.reject_biographic_set(operation_id=biographic_operation.id)
    else:
        actions.reject_biographic_set(operation_id=biographic_operation.id)

    client.reject.assert_called_once_with()
    assert append_log.call_args.kwargs["action"] == DeduplicationLogAction.REJECT_SET
    assert append_log.call_args.kwargs["result"]["success"] is (error is None)


def test_reject_unknown_operation(mocker: MockerFixture) -> None:
    mocker.patch.object(actions, "make_biographic_client")

    with pytest.raises(Exception):  # noqa: B017, PT011
        actions.reject_biographic_set(operation_id=uuid4())
