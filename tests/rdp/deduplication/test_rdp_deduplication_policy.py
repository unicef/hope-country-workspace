import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp
from country_workspace.rdp.deduplication.policy import ProgramDedupSettingsPolicy


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("enabled", [True, False])
def test_update_dedup_settings_visibility(program, enabled: bool) -> None:
    program.biometric_deduplication_enabled = enabled

    assert ProgramDedupSettingsPolicy(program).is_update_dedup_settings_visible() is enabled


def test_update_dedup_settings_check_when_disabled(program) -> None:
    program.biometric_deduplication_enabled = False

    assert ProgramDedupSettingsPolicy(program).update_dedup_settings_check().allowed is False


@pytest.mark.parametrize("blocked", [True, False])
def test_update_dedup_settings_check(
    program,
    mocker: MockerFixture,
    blocked: bool,
) -> None:
    program.biometric_deduplication_enabled = True
    policy = ProgramDedupSettingsPolicy(program)
    mocker.patch.object(policy, "_has_blocking_rdp", return_value=blocked)
    remote = mocker.patch.object(policy, "_has_blocking_deduplication_set", return_value=False)

    assert policy.update_dedup_settings_check().allowed is not blocked
    assert remote.called is not blocked


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


@pytest.mark.parametrize("can_create", [True, False])
def test_has_blocking_deduplication_set(
    program,
    mocker: MockerFixture,
    can_create: bool,
) -> None:
    from country_workspace.rdp.deduplication import policy as policy_mod

    make_client = mocker.patch.object(policy_mod, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    client.can_create_deduplication_set.return_value = can_create

    assert ProgramDedupSettingsPolicy(program)._has_blocking_deduplication_set() is not can_create
    make_client.assert_called_once_with(program.unicef_id)
