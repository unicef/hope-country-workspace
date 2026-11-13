from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication import processing
from country_workspace.rdp.deduplication.processing import RemoteFailure
from country_workspace.rdp.exceptions import RdpWorkflowError

pytestmark = pytest.mark.django_db


@pytest.fixture
def fail(mocker: MockerFixture):
    return mocker.patch.object(processing, "fail_rdp_operation", return_value=True)


@pytest.fixture
def complete(mocker: MockerFixture):
    return mocker.patch.object(processing, "complete_rdp_operation", return_value=True)


def _sync(operation: RdpOperation, fetch, operation_type: RdpOperation.Type | None = None) -> bool:
    return processing.sync_remote_result(
        operation,
        operation_type=operation_type or operation.operation_type,
        fetch=fetch,
    )


@pytest.mark.parametrize("fixture", ["biometric_operation", "successful_biometric_operation"])
def test_sync_ignores_an_operation_that_is_not_running(
    request: pytest.FixtureRequest, fixture: str, mocker: MockerFixture
) -> None:
    fetch = mocker.Mock()

    assert _sync(request.getfixturevalue(fixture), fetch) is False
    fetch.assert_not_called()


def test_sync_ignores_an_operation_of_another_type(
    running_biometric_operation: RdpOperation, mocker: MockerFixture
) -> None:
    fetch = mocker.Mock()

    assert _sync(running_biometric_operation, fetch, RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION) is False
    fetch.assert_not_called()


def test_sync_waits_while_the_remote_set_is_working(
    running_biometric_operation: RdpOperation, mocker: MockerFixture, fail, complete
) -> None:
    assert _sync(running_biometric_operation, mocker.Mock(return_value=None)) is False
    fail.assert_not_called()
    complete.assert_not_called()


def test_sync_completes_with_findings(
    running_biometric_operation: RdpOperation, mocker: MockerFixture, fail, complete
) -> None:
    findings: list = []

    assert _sync(running_biometric_operation, mocker.Mock(return_value=findings)) is True
    complete.assert_called_once_with(operation=running_biometric_operation, findings=findings)
    fail.assert_not_called()


def test_sync_fails_with_a_remote_failure(
    running_biometric_operation: RdpOperation, mocker: MockerFixture, fail, complete
) -> None:
    error = {"message": "boom"}

    assert _sync(running_biometric_operation, mocker.Mock(return_value=RemoteFailure(error))) is True
    fail.assert_called_once_with(
        operation_id=running_biometric_operation.id,
        error=error,
        expected_attempt=running_biometric_operation.attempt,
    )
    complete.assert_not_called()


@pytest.mark.parametrize("error", [RemoteError("bad"), RemoteUnavailableError("down")])
def test_sync_fails_when_the_remote_cannot_be_read(
    running_biometric_operation: RdpOperation, mocker: MockerFixture, fail, complete, error: Exception
) -> None:
    assert _sync(running_biometric_operation, mocker.Mock(side_effect=error)) is True
    fail.assert_called_once_with(
        operation_id=running_biometric_operation.id,
        error={"message": str(error)},
        expected_attempt=running_biometric_operation.attempt,
    )
    complete.assert_not_called()


@pytest.fixture
def callback_url(mocker: MockerFixture):
    return mocker.patch.object(processing, "build_dedup_operation_callback_url", return_value="https://cb")


def _get_or_create(operation: RdpOperation, mocker: MockerFixture, **overrides):
    arguments = {
        "label": "set",
        "retrieve": mocker.Mock(return_value=None),
        "create": mocker.Mock(return_value={"id": str(operation.id)}),
        "remote_id": lambda payload: payload["id"],
        "has_input": lambda: True,
        "no_input_error": {"message": "nothing to send"},
    } | overrides
    return processing.get_or_create_remote_set(operation, **arguments), arguments


def test_get_or_create_returns_the_existing_set(
    biometric_operation: RdpOperation, mocker: MockerFixture, callback_url
) -> None:
    existing = {"id": "existing"}

    payload, arguments = _get_or_create(
        biometric_operation, mocker, retrieve=mocker.Mock(return_value=existing), has_input=mocker.Mock()
    )

    assert payload is existing
    arguments["has_input"].assert_not_called()
    arguments["create"].assert_not_called()


def test_get_or_create_creates_the_set_with_the_callback(
    biometric_operation: RdpOperation, mocker: MockerFixture, callback_url
) -> None:
    before_create = mocker.Mock()

    payload, arguments = _get_or_create(biometric_operation, mocker, before_create=before_create)

    assert payload == {"id": str(biometric_operation.id)}
    before_create.assert_called_once_with()
    callback_url.assert_called_once_with(operation_id=biometric_operation.id)
    arguments["create"].assert_called_once_with("https://cb")


def test_get_or_create_requires_input(biometric_operation: RdpOperation, mocker: MockerFixture, callback_url) -> None:
    before_create = mocker.Mock()

    with pytest.raises(RdpWorkflowError):
        _get_or_create(biometric_operation, mocker, has_input=lambda: False, before_create=before_create)

    before_create.assert_not_called()


def test_get_or_create_stops_when_creation_is_not_allowed(
    biometric_operation: RdpOperation, mocker: MockerFixture, callback_url
) -> None:
    create = mocker.Mock()

    with pytest.raises(RemoteError, match="busy"):
        _get_or_create(
            biometric_operation,
            mocker,
            create=create,
            before_create=mocker.Mock(side_effect=RemoteError("busy")),
        )

    create.assert_not_called()


def test_get_or_create_rejects_an_id_mismatch(
    biometric_operation: RdpOperation, mocker: MockerFixture, callback_url
) -> None:
    other = str(uuid4())

    with pytest.raises(RemoteError, match=rf"dataset id mismatch: expected={biometric_operation.id}, got='{other}'"):
        _get_or_create(
            biometric_operation,
            mocker,
            label="dataset",
            create=mocker.Mock(return_value={"id": other}),
        )
