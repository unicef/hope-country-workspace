import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.rdp.deduplication.biometric.policy import ProgramDedupSettingsPolicy


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("enabled", [True, False])
def test_update_dedup_settings_visibility(program, enabled: bool) -> None:
    program.biometric_deduplication_enabled = enabled

    assert ProgramDedupSettingsPolicy(program).is_update_dedup_settings_visible() is enabled


def test_update_dedup_settings_check_when_disabled(program) -> None:
    program.biometric_deduplication_enabled = False

    assert ProgramDedupSettingsPolicy(program).update_dedup_settings_check().allowed is False


def test_update_dedup_settings_check_when_cleanup_in_progress(
    program: Program,
    mocker: MockerFixture,
) -> None:
    program.cleanup_in_progress = True
    program.biometric_deduplication_enabled = True
    policy = ProgramDedupSettingsPolicy(program)
    remote_check = mocker.patch.object(policy, "_has_blocking_deduplication_set")

    check = policy.update_dedup_settings_check()

    assert check.allowed is False
    assert "cleanup" in (check.reason or "")
    remote_check.assert_not_called()


@pytest.mark.parametrize(("local_blocked", "remote_blocked"), [(True, False), (False, True), (False, False)])
def test_update_dedup_settings_check(
    program: Program,
    mocker: MockerFixture,
    local_blocked: bool,
    remote_blocked: bool,
) -> None:
    program.biometric_deduplication_enabled = True
    policy = ProgramDedupSettingsPolicy(program)
    mocker.patch.object(policy, "_has_blocking_rdp", return_value=local_blocked)
    remote = mocker.patch.object(policy, "_has_blocking_deduplication_set", return_value=remote_blocked)

    assert policy.update_dedup_settings_check().allowed is not (local_blocked or remote_blocked)
    assert remote.called is not local_blocked


@pytest.mark.parametrize(
    "error",
    [RemoteError("remote"), RemoteUnavailableError("unavailable")],
    ids=["remote_error", "unavailable"],
)
def test_update_dedup_settings_check_when_remote_error(
    program,
    mocker: MockerFixture,
    error: Exception,
) -> None:
    program.biometric_deduplication_enabled = True
    policy = ProgramDedupSettingsPolicy(program)
    mocker.patch.object(policy, "_has_blocking_rdp", return_value=False)
    mocker.patch.object(policy, "_has_blocking_deduplication_set", side_effect=error)

    assert policy.update_dedup_settings_check().allowed is False


@pytest.mark.parametrize(
    ("status", "with_operation", "expected"),
    [
        (Rdp.PushStatus.SUCCESS, False, True),
        (Rdp.PushStatus.REVIEW_PENDING, False, True),
        (Rdp.PushStatus.PUSH_PENDING, False, True),
        (Rdp.PushStatus.PENDING, False, False),
        (Rdp.PushStatus.PENDING, True, True),
        (Rdp.PushStatus.FAILURE, True, True),
        (Rdp.PushStatus.CANCELLED, True, False),
    ],
)
def test_has_blocking_rdp(
    program,
    status: Rdp.PushStatus,
    with_operation: bool,
    expected: bool,
) -> None:
    from testutils.factories import BiometricRdpOperationFactory, RdpFactory

    rdp = RdpFactory(program=program, status=status)
    if with_operation:
        BiometricRdpOperationFactory(rdp=rdp)

    assert ProgramDedupSettingsPolicy(program)._has_blocking_rdp() is expected


def test_has_blocking_rdp_ignores_ocr_operation(ocr_operation: RdpOperation) -> None:
    assert not ProgramDedupSettingsPolicy(ocr_operation.rdp.program)._has_blocking_rdp()


@pytest.mark.parametrize("can_create", [True, False])
def test_has_blocking_deduplication_set(
    program,
    mocker: MockerFixture,
    can_create: bool,
) -> None:
    from country_workspace.rdp.deduplication.biometric import policy as policy_mod

    make_client = mocker.patch.object(policy_mod, "make_biometric_client")
    client = make_client.return_value.__enter__.return_value
    client.can_create_deduplication_set.return_value = can_create

    assert ProgramDedupSettingsPolicy(program)._has_blocking_deduplication_set() is not can_create
    make_client.assert_called_once_with(program.unicef_id)
