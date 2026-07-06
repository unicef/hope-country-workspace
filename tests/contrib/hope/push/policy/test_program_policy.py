from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState, RUNNING_DEDUPLICATION_SET_STATES
from country_workspace.contrib.hope.push.policy import ProgramDedupSettingsPolicy, RdpActionPolicy
from country_workspace.models import Rdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def dedup_program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(biometric_deduplication_enabled=True)


@pytest.fixture
def non_dedup_program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(biometric_deduplication_enabled=False)


@pytest.fixture
def make_program_rdp():
    from testutils.factories import CountryRdpFactory

    def factory(program, *, status: str, locked: bool = False, deduplication_set_id=None):
        return CountryRdpFactory(
            program=program,
            status=status,
            is_dedup_settings_locked=locked,
            deduplication_set_id=deduplication_set_id,
        )

    return factory


# -------------------------- lock detection --------------------------


@pytest.mark.parametrize(
    ("status", "locked", "expected"),
    [
        (Rdp.PushStatus.SUCCESS, False, True),
        (Rdp.PushStatus.PENDING, True, True),
        (Rdp.PushStatus.PENDING, False, False),
        (Rdp.PushStatus.FAILURE, True, True),
        (Rdp.PushStatus.CANCELLED, True, False),
    ],
    ids=["success", "pending_locked", "pending_unlocked", "failure_locked", "cancelled_locked"],
)
def test_program_dedup_settings_policy_has_db_locked_dedup_settings(
    dedup_program,
    make_program_rdp,
    status: str,
    locked: bool,
    expected: bool,
) -> None:
    make_program_rdp(dedup_program, status=status, locked=locked)

    assert ProgramDedupSettingsPolicy(dedup_program)._has_db_locked_dedup_settings() is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (RUNNING_DEDUPLICATION_SET_STATES[0], True),
        (DeduplicationSetState.DEDUPLICATED, False),
        (None, False),
    ],
    ids=["running", "not_running", "none"],
)
def test_program_dedup_settings_policy_has_running_deduplication_set(
    mocker: MockerFixture,
    dedup_program,
    make_program_rdp,
    state,
    expected: bool,
) -> None:
    make_program_rdp(
        dedup_program,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id=uuid4(),
    )
    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    assert ProgramDedupSettingsPolicy(dedup_program)._has_running_deduplication_set() is expected


# -------------------------- update check ----------------------------


def test_program_dedup_settings_policy_update_dedup_settings_check_disabled(non_dedup_program) -> None:
    check = ProgramDedupSettingsPolicy(non_dedup_program).update_dedup_settings_check()

    assert check.allowed is False
    assert check.reason is not None
    assert "biometric deduplication is not enabled" in check.reason


@pytest.mark.parametrize(
    ("status", "locked", "allowed", "reason"),
    [
        (Rdp.PushStatus.PENDING, False, True, None),
        (Rdp.PushStatus.PENDING, True, False, "cannot be updated"),
        (Rdp.PushStatus.SUCCESS, False, False, "cannot be updated"),
        (Rdp.PushStatus.FAILURE, True, False, "cannot be updated"),
    ],
    ids=["allowed", "pending_locked", "success", "failure_locked"],
)
def test_program_dedup_settings_policy_update_dedup_settings_check(
    mocker: MockerFixture,
    dedup_program,
    make_program_rdp,
    status: str,
    locked: bool,
    allowed: bool,
    reason: str | None,
) -> None:
    mocker.patch.object(ProgramDedupSettingsPolicy, "_has_running_deduplication_set", return_value=False)
    make_program_rdp(dedup_program, status=status, locked=locked)

    check = ProgramDedupSettingsPolicy(dedup_program).update_dedup_settings_check()

    assert check.allowed is allowed
    if reason is None:
        assert check.reason is None
    else:
        assert check.reason is not None
        assert reason in check.reason


def test_program_dedup_settings_policy_update_dedup_settings_check_blocks_running_dedup_set(
    mocker: MockerFixture,
    dedup_program,
) -> None:
    mocker.patch.object(ProgramDedupSettingsPolicy, "_has_db_locked_dedup_settings", return_value=False)
    mocker.patch.object(ProgramDedupSettingsPolicy, "_has_running_deduplication_set", return_value=True)

    check = ProgramDedupSettingsPolicy(dedup_program).update_dedup_settings_check()

    assert check.allowed is False
    assert check.reason is not None
    assert "cannot be updated" in check.reason
