from typing import cast
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import (
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    PUSHABLE_DEDUPLICATION_SET_STATES,
    RUNNING_DEDUPLICATION_SET_STATES,
    DedupClientStatus,
    DedupResponseStatus,
    DeduplicationSetState,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import (
    ActionCheck,
    DedupEngineState,
    ProgramDedupSettingsPolicy,
    RdpActionPolicy,
    get_program_dedup_settings_policy,
    get_rdp_policy,
    require_policy_check,
)

MOD = "country_workspace.rdp.policy"

pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryProgramFactory, CountryRdpFactory

    program = CountryProgramFactory(biometric_deduplication_enabled=True)
    return CountryRdpFactory(
        program=program,
        pushed_by=user,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id=uuid4(),
        is_dedup_settings_locked=False,
    )


@pytest.fixture(
    params=[
        (False, None, False, False),
        (True, None, False, True),
        (True, Rdp.PushStatus.SUCCESS, False, False),
        (True, Rdp.PushStatus.PENDING, True, False),
        (True, Rdp.PushStatus.FAILURE, True, False),
        (True, Rdp.PushStatus.PUSH_PENDING, False, False),
    ],
    ids=["disabled", "allowed", "success", "pending_locked", "failure_locked", "push_pending"],
)
def program_case(request: pytest.FixtureRequest, user):
    from testutils.factories import CountryProgramFactory, CountryRdpFactory

    biometric, status, locked, allowed = request.param
    program = CountryProgramFactory(biometric_deduplication_enabled=biometric)
    if status is not None:
        CountryRdpFactory(
            program=program,
            pushed_by=user,
            status=status,
            is_dedup_settings_locked=locked,
        )
    return program, biometric, allowed


@pytest.fixture(
    params=[
        (RUNNING_DEDUPLICATION_SET_STATES[0], False),
        (PUSHABLE_DEDUPLICATION_SET_STATES[0], True),
    ],
    ids=["running", "finished"],
)
def program_dedup_state_case(request: pytest.FixtureRequest, user):
    from testutils.factories import CountryProgramFactory, CountryRdpFactory

    state, allowed = request.param
    program = CountryProgramFactory(biometric_deduplication_enabled=True)
    CountryRdpFactory(
        program=program,
        pushed_by=user,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id=uuid4(),
        is_dedup_settings_locked=False,
    )
    return program, state, allowed


@pytest.fixture(params=["not_success", "latest", "older"], ids=["not_success", "latest", "older"])
def reset_case(request: pytest.FixtureRequest, user):
    from testutils.factories import CountryProgramFactory, CountryRdpFactory

    program = CountryProgramFactory()
    status = Rdp.PushStatus.PENDING if request.param == "not_success" else Rdp.PushStatus.SUCCESS
    rdp = CountryRdpFactory(program=program, pushed_by=user, status=status)

    if request.param == "older":
        CountryRdpFactory(program=program, pushed_by=user, status=Rdp.PushStatus.SUCCESS)

    return rdp, request.param == "latest"


@pytest.mark.parametrize(
    "case",
    [
        (True, None, None),
        (False, "blocked", "blocked"),
        (False, None, "Action is not allowed"),
    ],
    ids=["allowed", "reason", "default_reason"],
)
def test_action_check_require(case) -> None:
    allowed, reason, error = case
    check = ActionCheck(allowed, reason)

    if error is None:
        check.require()
    else:
        with pytest.raises(RdpWorkflowError, match=error):
            check.require()


@pytest.mark.parametrize(
    "case",
    [
        (DedupEngineState(), "-"),
        (DedupEngineState(can_create_deduplication_set=True), "Ready to start"),
        (DedupEngineState(can_create_deduplication_set=False), "Can't create deduplication set"),
        (DedupEngineState.unavailable(), DedupResponseStatus.STATUS_UNAVAILABLE.value),
        (
            DedupEngineState(status=DedupClientStatus(DedupResponseStatus.OK, None, -1)),
            "Created / waiting for status",
        ),
        (
            DedupEngineState(status=DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 2)),
            "Ready / 2 findings",
        ),
        (
            DedupEngineState(status=DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, -1)),
            "Ready",
        ),
        (
            DedupEngineState(status=DedupClientStatus(cast("DedupResponseStatus", "error"), None, -1)),
            "Remote error",
        ),
    ],
    ids=["empty", "ready", "cannot_create", "unavailable", "waiting", "findings", "state", "remote_error"],
)
def test_dedup_engine_state_str(case) -> None:
    state, expected = case

    assert str(state) == expected


def test_program_policy(program_case) -> None:
    program, biometric, allowed = program_case
    policy = get_program_dedup_settings_policy(program)

    assert policy.is_update_dedup_settings_visible() is biometric
    assert policy.update_dedup_settings_check().allowed is allowed


def test_program_policy_running_dedup(program_dedup_state_case, mocker: MockerFixture) -> None:
    program, state, allowed = program_dedup_state_case
    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    assert ProgramDedupSettingsPolicy(program).update_dedup_settings_check().allowed is allowed


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.PENDING, True, True, True),
        (Rdp.PushStatus.FAILURE, True, True, True),
        (Rdp.PushStatus.PENDING, False, False, True),
        (Rdp.PushStatus.SUCCESS, True, False, False),
    ],
    ids=["pending", "failure", "non_biometric", "closed"],
)
def test_rdp_visibility(rdp: Rdp, case) -> None:
    status, biometric, deduplicate, open_actions = case
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = biometric

    policy = get_rdp_policy(rdp)

    assert policy.is_deduplicate_visible() is deduplicate
    assert policy.is_cancel_visible() is open_actions
    assert policy.is_push_visible() is open_actions
    assert get_rdp_policy(rdp) is policy


@pytest.mark.parametrize("has_set", [False, True], ids=["without_set", "with_set"])
def test_deduplication_status(rdp: Rdp, mocker: MockerFixture, has_set: bool) -> None:
    rdp.deduplication_set_id = uuid4() if has_set else None
    status = DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 0)
    remote = mocker.patch(f"{MOD}.get_deduplication_status", return_value=status)

    result = RdpActionPolicy.deduplication_status(rdp)

    assert result == (status if has_set else None)
    assert remote.called is has_set


def test_dedup_engine_access(rdp: Rdp, mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = True
    client.retrieve_deduplication_set.return_value = {"state": DeduplicationSetState.READY}
    context = mocker.MagicMock()
    context.__enter__.return_value = client
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=context)

    policy = RdpActionPolicy(rdp)

    assert policy.can_create_deduplication_set is True
    assert policy.can_create_deduplication_set is True
    assert policy.deduplication_set_state == DeduplicationSetState.READY
    assert make_client.call_count == 2

    rdp.deduplication_set_id = None
    assert RdpActionPolicy(rdp).deduplication_set_state is None
    assert make_client.call_count == 2


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.SUCCESS, True, True, True, PROCESSABLE_DEDUPLICATION_SET_STATES[0], False),
        (Rdp.PushStatus.PENDING, False, True, True, PROCESSABLE_DEDUPLICATION_SET_STATES[0], False),
        (Rdp.PushStatus.PENDING, True, True, True, None, True),
        (Rdp.PushStatus.PENDING, True, False, False, None, False),
        (Rdp.PushStatus.PENDING, True, True, False, PROCESSABLE_DEDUPLICATION_SET_STATES[0], True),
        (Rdp.PushStatus.PENDING, True, True, False, "Other", False),
    ],
    ids=["closed", "non_biometric", "can_create", "no_set", "processable", "not_processable"],
)
def test_deduplicate_check(rdp: Rdp, mocker: MockerFixture, case) -> None:
    status, biometric, has_set, can_create, state, allowed = case
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = biometric
    rdp.deduplication_set_id = uuid4() if has_set else None

    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=can_create,
    )
    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    assert RdpActionPolicy(rdp).deduplicate_check().allowed is allowed


@pytest.mark.parametrize("locked", [True, False], ids=["locked", "unlocked"])
def test_claim_deduplication_check(rdp: Rdp, mocker: MockerFixture, locked: bool) -> None:
    rdp.is_dedup_settings_locked = locked
    deduplicate = mocker.patch.object(RdpActionPolicy, "deduplicate_check", return_value=ActionCheck(True))

    assert RdpActionPolicy(rdp).claim_deduplication_check().allowed is not locked
    assert deduplicate.called is not locked


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.SUCCESS, False, True, True, "Other", False),
        (Rdp.PushStatus.PENDING, True, True, True, "Other", False),
        (Rdp.PushStatus.PENDING, False, False, True, "Other", True),
        (Rdp.PushStatus.PENDING, False, True, False, "Other", True),
        (Rdp.PushStatus.PENDING, False, True, True, RUNNING_DEDUPLICATION_SET_STATES[0], False),
        (Rdp.PushStatus.PENDING, False, True, True, "Other", True),
    ],
    ids=["closed", "locked", "non_biometric", "no_set", "running", "allowed"],
)
def test_cancel_check(rdp: Rdp, mocker: MockerFixture, case) -> None:
    status, locked, biometric, has_set, state, allowed = case
    rdp.status = status
    rdp.is_dedup_settings_locked = locked
    rdp.program.biometric_deduplication_enabled = biometric
    rdp.deduplication_set_id = uuid4() if has_set else None

    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    assert RdpActionPolicy(rdp).cancel_check().allowed is allowed


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.SUCCESS, True, True, PUSHABLE_DEDUPLICATION_SET_STATES[0], False),
        (Rdp.PushStatus.PENDING, False, True, PUSHABLE_DEDUPLICATION_SET_STATES[0], True),
        (Rdp.PushStatus.PENDING, True, False, None, False),
        (Rdp.PushStatus.PENDING, True, True, PUSHABLE_DEDUPLICATION_SET_STATES[0], True),
        (Rdp.PushStatus.PENDING, True, True, "Other", False),
    ],
    ids=["closed", "non_biometric", "no_set", "pushable", "not_pushable"],
)
def test_push_check(rdp: Rdp, mocker: MockerFixture, case) -> None:
    status, biometric, has_set, state, allowed = case
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = biometric
    rdp.deduplication_set_id = uuid4() if has_set else None

    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    assert RdpActionPolicy(rdp).push_check().allowed is allowed


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.PUSH_PENDING, False, False),
        (Rdp.PushStatus.PENDING, True, False),
        (Rdp.PushStatus.PENDING, False, True),
    ],
    ids=["already_pending", "dedup_locked", "delegate"],
)
def test_start_push_check(rdp: Rdp, mocker: MockerFixture, case) -> None:
    status, locked, delegated = case
    rdp.status = status
    rdp.is_dedup_settings_locked = locked
    push = mocker.patch.object(RdpActionPolicy, "push_check", return_value=ActionCheck(True))

    assert RdpActionPolicy(rdp).start_push_check().allowed is delegated
    assert push.called is delegated


def test_reset_check(reset_case) -> None:
    rdp, allowed = reset_case

    assert RdpActionPolicy(rdp).reset_check().allowed is allowed


@pytest.mark.parametrize(
    "case",
    [
        ("closed", DedupEngineState()),
        ("none", DedupEngineState(can_create_deduplication_set=False)),
        (
            "status",
            DedupEngineState(status=DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 0)),
        ),
        ("remote", DedupEngineState(can_create_deduplication_set=True)),
    ],
    ids=["closed", "without_status", "with_status", "remote_fallback"],
)
def test_dedup_engine_state(rdp: Rdp, mocker: MockerFixture, case) -> None:
    scenario, expected = case
    status = expected.status

    rdp.status = Rdp.PushStatus.SUCCESS if scenario == "closed" else Rdp.PushStatus.PENDING
    remote = mocker.patch.object(
        RdpActionPolicy,
        "deduplication_status",
        side_effect=RemoteError("boom") if scenario == "remote" else None,
        return_value=status,
    )
    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=expected.can_create_deduplication_set,
    )

    assert RdpActionPolicy(rdp).dedup_engine_state() == expected
    assert remote.called is (scenario != "closed")


def test_dedup_engine_state_reraises_remote_error(rdp: Rdp, mocker: MockerFixture) -> None:
    mocker.patch.object(RdpActionPolicy, "deduplication_status", side_effect=RemoteError("boom"))
    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=False,
    )

    with pytest.raises(RemoteError, match="boom"):
        RdpActionPolicy(rdp).dedup_engine_state()


@pytest.mark.parametrize("case", ["allowed", "denied", "remote"], ids=["allowed", "denied", "remote"])
def test_require_policy_check(mocker: MockerFixture, case: str) -> None:
    check = mocker.Mock()

    if case == "allowed":
        check.return_value = ActionCheck(True)
        require_policy_check(check)
        return

    if case == "denied":
        check.return_value = ActionCheck(False, "blocked")
    else:
        check.side_effect = RemoteUnavailableError("boom")

    with pytest.raises(RdpWorkflowError):
        require_policy_check(check)
