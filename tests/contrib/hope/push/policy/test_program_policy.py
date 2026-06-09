import pytest

from country_workspace.contrib.hope.push.policy import ProgramDedupSettingsPolicy
from country_workspace.models import Rdp


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

    def factory(program, *, status: str, locked: bool = False):
        return CountryRdpFactory(
            program=program,
            status=status,
            is_dedup_settings_locked=locked,
        )

    return factory


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "locked", "expected"),
    [
        (Rdp.PushStatus.PUSHED, False, True),
        (Rdp.PushStatus.MERGED, False, True),
        (Rdp.PushStatus.PENDING, True, True),
        (Rdp.PushStatus.PENDING, False, False),
        (Rdp.PushStatus.FAILURE, True, False),
        (Rdp.PushStatus.REJECTED, True, False),
    ],
    ids=["pushed", "merged", "pending_locked", "pending_unlocked", "failure_locked", "rejected_locked"],
)
def test_program_dedup_settings_policy_has_locked_dedup_settings(
    dedup_program,
    make_program_rdp,
    status: str,
    locked: bool,
    expected: bool,
) -> None:
    make_program_rdp(dedup_program, status=status, locked=locked)

    assert ProgramDedupSettingsPolicy(dedup_program)._has_locked_dedup_settings() is expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "locked", "allowed", "reason"),
    [
        (Rdp.PushStatus.PENDING, False, True, None),
        (Rdp.PushStatus.PENDING, True, False, "cannot be updated"),
        (Rdp.PushStatus.PUSHED, False, False, "cannot be updated"),
        (Rdp.PushStatus.MERGED, False, False, "cannot be updated"),
    ],
    ids=["allowed", "pending_locked", "pushed", "merged"],
)
def test_program_dedup_settings_policy_update_dedup_settings_check(
    dedup_program,
    make_program_rdp,
    status: str,
    locked: bool,
    allowed: bool,
    reason: str | None,
) -> None:
    make_program_rdp(dedup_program, status=status, locked=locked)

    check = ProgramDedupSettingsPolicy(dedup_program).update_dedup_settings_check()

    assert check.allowed is allowed
    if reason is None:
        assert check.reason is None
    else:
        assert check.reason is not None
        assert reason in check.reason


@pytest.mark.django_db
def test_program_dedup_settings_policy_update_dedup_settings_check_disabled(non_dedup_program) -> None:
    check = ProgramDedupSettingsPolicy(non_dedup_program).update_dedup_settings_check()

    assert check.allowed is False
    assert check.reason is not None
    assert "biometric deduplication is not enabled" in check.reason
