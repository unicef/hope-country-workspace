from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.deduplication.operations import (
    approve_deduplication_set_after_successful_push,
    reject_deduplication_set,
)

MOD = "country_workspace.rdp.deduplication.operations"

pytestmark = pytest.mark.django_db


def test_approve_deduplication_set_without_set(mocker: MockerFixture) -> None:
    make_client = mocker.patch(f"{MOD}.make_dedup_client")
    append_log = mocker.patch(f"{MOD}.append_rdp_operation_log")

    approve_deduplication_set_after_successful_push(
        rdp_id=1,
        group_reference_id="PROGRAM",
        deduplication_set_id=None,
    )

    make_client.assert_not_called()
    append_log.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [None, RemoteError("boom"), RemoteUnavailableError("boom")],
    ids=["success", "remote_error", "unavailable"],
)
def test_approve_deduplication_set(mocker: MockerFixture, error: Exception | None) -> None:
    deduplication_set_id = uuid4()
    client = mocker.MagicMock()
    if error:
        client.approve.side_effect = error

    context = mocker.MagicMock()
    context.__enter__.return_value = client
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=context)

    rdp = mocker.MagicMock()
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    append_log = mocker.patch(f"{MOD}.append_rdp_operation_log")

    approve_deduplication_set_after_successful_push(
        rdp_id=1,
        group_reference_id="PROGRAM",
        deduplication_set_id=deduplication_set_id,
    )

    make_client.assert_called_once_with("PROGRAM", deduplication_set_id=str(deduplication_set_id))
    client.approve.assert_called_once_with()
    append_log.assert_called_once_with(
        rdp=rdp,
        action=RdpOperationAction.APPROVE_DEDUPLICATION_SET,
        result={
            "deduplication_set_id": str(deduplication_set_id),
            "success": error is None,
            **({"error": "boom"} if error else {}),
        },
    )


def test_reject_deduplication_set(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    context = mocker.MagicMock()
    context.__enter__.return_value = client
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=context)

    reject_deduplication_set(group_reference_id="PROGRAM", deduplication_set_id="DS")

    make_client.assert_called_once_with("PROGRAM", deduplication_set_id="DS")
    client.reject.assert_called_once_with()
