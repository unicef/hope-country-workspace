import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import (
    DedupClientStatus,
    DedupResponseStatus,
    DeduplicationSetState,
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    PUSHABLE_DEDUPLICATION_SET_STATES,
    RUNNING_DEDUPLICATION_SET_STATES,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.push.policy import (
    ActionCheck,
    DedupEngineState,
    RdpActionPolicy,
    get_rdp_policy,
)
from country_workspace.exceptions import RemoteError
from country_workspace.models import Rdp

MOD = "country_workspace.contrib.hope.push.policy"


@pytest.fixture
def rdp(mocker: MockerFixture):
    program = mocker.MagicMock(
        biometric_deduplication_enabled=True,
        unicef_id="program-1",
    )
    rdp = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id="ds-1",
        is_dedup_settings_locked=False,
        is_push_locked=False,
        program=program,
    )
    rdp.PushStatus = Rdp.PushStatus
    return rdp


# ----------------------------- action check -----------------------------


def test_action_check_require_enabled() -> None:
    ActionCheck(True).require()


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("boom", "boom"),
        (None, "Action is not allowed."),
    ],
    ids=["custom_reason", "default_reason"],
)
def test_action_check_require_disabled(reason: str | None, expected: str, err_contains) -> None:
    with pytest.raises(HopePushError) as exc:
        ActionCheck(False, reason).require()
    assert err_contains(exc.value.args[0]["errors"], expected)


# -------------------------- dedup engine access -------------------------


def test_deduplication_status_without_set_id(rdp) -> None:
    rdp.deduplication_set_id = ""
    assert RdpActionPolicy.deduplication_status(rdp) is None


def test_deduplication_status_calls_remote(mocker: MockerFixture, rdp) -> None:
    status = DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=DeduplicationSetState.READY,
        findings_count=0,
    )
    spy = mocker.patch(f"{MOD}.get_deduplication_status", return_value=status)
    assert RdpActionPolicy.deduplication_status(rdp) == status
    spy.assert_called_once_with(group_reference_id="program-1", deduplication_set_id="ds-1")


def test_can_create_deduplication_set_cached_property(
    mocker: MockerFixture,
    rdp,
    dedup_api_cm,
) -> None:
    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = True
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    policy = RdpActionPolicy(rdp)

    assert policy.can_create_deduplication_set is True
    assert policy.can_create_deduplication_set is True

    make_client.assert_called_once_with("program-1")
    client.can_create_deduplication_set.assert_called_once_with()


def test_deduplication_set_state_without_set_id(mocker: MockerFixture, rdp) -> None:
    rdp.deduplication_set_id = None
    make_client = mocker.patch(f"{MOD}.make_dedup_client")

    assert RdpActionPolicy(rdp).deduplication_set_state is None

    make_client.assert_not_called()


def test_deduplication_set_state_cached_property(
    mocker: MockerFixture,
    rdp,
    dedup_api_cm,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set.return_value = {"state": DeduplicationSetState.READY}
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    policy = RdpActionPolicy(rdp)

    assert policy.deduplication_set_state == DeduplicationSetState.READY
    assert policy.deduplication_set_state == DeduplicationSetState.READY

    make_client.assert_called_once_with("program-1", deduplication_set_id="ds-1")
    client.retrieve_deduplication_set.assert_called_once_with()


# ------------------------------ visibility ------------------------------


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "expected"),
    [
        (Rdp.PushStatus.PENDING, True, "ds-1", (True, True, True)),
        (Rdp.PushStatus.PENDING, True, "", (True, True, True)),
        (Rdp.PushStatus.PENDING, False, "ds-1", (False, True, True)),
        (Rdp.PushStatus.FAILURE, True, "ds-1", (True, True, True)),
        (Rdp.PushStatus.SUCCESS, True, "ds-1", (False, False, False)),
    ],
    ids=["pending_with_set", "pending_without_set", "pending_disabled", "failure", "non_open"],
)
def test_visibility_methods(
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    expected: tuple[bool, bool, bool],
) -> None:
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled
    rdp.deduplication_set_id = set_id
    policy = RdpActionPolicy(rdp)

    assert (
        policy.is_deduplicate_visible(),
        policy.is_cancel_visible(),
        policy.is_push_visible(),
    ) == expected


# ------------------------------- dedup ----------------------------------


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "can_create", "allowed", "reason"),
    [
        (
            Rdp.PushStatus.SUCCESS,
            True,
            "ds-1",
            DeduplicationSetState.READY,
            True,
            False,
            "can not run dedup",
        ),
        (
            Rdp.PushStatus.PENDING,
            False,
            "ds-1",
            DeduplicationSetState.READY,
            True,
            False,
            "biometric deduplication is not enabled",
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            None,
            False,
            False,
            "can not create deduplication set",
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            None,
            True,
            True,
            None,
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            DeduplicationSetState.APPROVED,
            True,
            True,
            None,
        ),
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                False,
                True,
                None,
            )
            for state in PROCESSABLE_DEDUPLICATION_SET_STATES
        ],
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                False,
                False,
                "can not process deduplication set",
            )
            for state in DeduplicationSetState
            if state not in PROCESSABLE_DEDUPLICATION_SET_STATES
        ],
    ],
    ids=[
        "not_pending",
        "disabled",
        "cannot_create_without_set",
        "can_create_without_set",
        "can_create_with_stale_set",
        *(f"processable_{state.name.lower()}" for state in PROCESSABLE_DEDUPLICATION_SET_STATES),
        *(
            f"blocked_{state.name.lower()}"
            for state in DeduplicationSetState
            if state not in PROCESSABLE_DEDUPLICATION_SET_STATES
        ),
    ],
)
def test_deduplicate_check(
    mocker: MockerFixture,
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    state: str | None,
    can_create: bool,
    allowed: bool,
    reason: str | None,
) -> None:
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled
    rdp.deduplication_set_id = set_id

    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )
    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=can_create,
    )

    check = RdpActionPolicy(rdp).deduplicate_check()

    assert check.allowed is allowed
    if reason is None:
        assert check.reason is None
    else:
        assert check.reason is not None
        assert reason in check.reason


def test_claim_deduplication_check_blocks_locked_active_dedup(
    mocker: MockerFixture,
    rdp,
) -> None:
    rdp.is_dedup_settings_locked = True
    deduplicate_check = mocker.patch.object(RdpActionPolicy, "deduplicate_check")

    check = RdpActionPolicy(rdp).claim_deduplication_check()

    assert check.allowed is False
    assert check.reason is not None
    assert "already been started" in check.reason
    deduplicate_check.assert_not_called()


def test_claim_deduplication_check_delegates_to_deduplicate_check(
    mocker: MockerFixture,
    rdp,
) -> None:
    expected = ActionCheck(True)
    rdp.is_dedup_settings_locked = False
    deduplicate_check = mocker.patch.object(
        RdpActionPolicy,
        "deduplicate_check",
        return_value=expected,
    )

    assert RdpActionPolicy(rdp).claim_deduplication_check() == expected
    deduplicate_check.assert_called_once_with()


# ------------------------------- cancel ---------------------------------


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "push_locked", "dedup_locked", "state", "allowed", "reason"),
    [
        (Rdp.PushStatus.SUCCESS, True, "ds-1", False, False, None, False, "can not cancel in status"),
        (Rdp.PushStatus.PENDING, True, "ds-1", True, False, None, False, "push to HOPE is queued or running"),
        (Rdp.PushStatus.PENDING, True, "ds-1", False, True, None, False, "deduplication is queued or running"),
        (Rdp.PushStatus.PENDING, False, "ds-1", False, False, None, True, None),
        (Rdp.PushStatus.PENDING, True, "", False, False, None, True, None),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            False,
            False,
            RUNNING_DEDUPLICATION_SET_STATES[0],
            False,
            "can not cancel RDP",
        ),
        (Rdp.PushStatus.PENDING, True, "ds-1", False, False, DeduplicationSetState.DEDUPLICATED, True, None),
    ],
    ids=["closed", "push_locked", "dedup_locked", "dedup_disabled", "missing_set", "running_set", "ok"],
)
def test_cancel_check(
    mocker: MockerFixture,
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    push_locked: bool,
    dedup_locked: bool,
    state: str | None,
    allowed: bool,
    reason: str | None,
) -> None:
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled
    rdp.deduplication_set_id = set_id
    rdp.is_push_locked = push_locked
    rdp.is_dedup_settings_locked = dedup_locked

    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    check = RdpActionPolicy(rdp).cancel_check()

    assert check.allowed is allowed
    if reason is None:
        assert check.reason is None
    else:
        assert check.reason is not None
        assert reason in check.reason


# -------------------------------- push ----------------------------------


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "allowed", "reason"),
    [
        (
            Rdp.PushStatus.SUCCESS,
            True,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            False,
            "can not push",
        ),
        (
            Rdp.PushStatus.PENDING,
            False,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            True,
            None,
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            DeduplicationSetState.DEDUPLICATED,
            False,
            "deduplication_set_id is not set",
        ),
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                True,
                None,
            )
            for state in PUSHABLE_DEDUPLICATION_SET_STATES
        ],
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                False,
                "can not push with deduplication set",
            )
            for state in DeduplicationSetState
            if state not in PUSHABLE_DEDUPLICATION_SET_STATES
        ],
    ],
    ids=[
        "not_pending",
        "disabled",
        "missing_set_id",
        *(f"pushable_{state.name.lower()}" for state in PUSHABLE_DEDUPLICATION_SET_STATES),
        *(
            f"blocked_{state.name.lower()}"
            for state in DeduplicationSetState
            if state not in PUSHABLE_DEDUPLICATION_SET_STATES
        ),
    ],
)
def test_push_check(
    mocker: MockerFixture,
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    state: str,
    allowed: bool,
    reason: str | None,
) -> None:
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled
    rdp.deduplication_set_id = set_id

    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_set_state",
        new_callable=mocker.PropertyMock,
        return_value=state,
    )

    check = RdpActionPolicy(rdp).push_check()

    assert check.allowed is allowed
    if reason is None:
        assert check.reason is None
    else:
        assert check.reason is not None
        assert reason in check.reason


def test_start_push_check_blocks_locked_push(mocker: MockerFixture, rdp) -> None:
    rdp.is_push_locked = True
    push_check = mocker.patch.object(RdpActionPolicy, "push_check")

    check = RdpActionPolicy(rdp).start_push_check()

    assert check.allowed is False
    assert check.reason is not None
    assert "already queued or running" in check.reason
    push_check.assert_not_called()


def test_start_push_check_delegates_to_push_check(mocker: MockerFixture, rdp) -> None:
    expected = ActionCheck(True)
    rdp.is_push_locked = False
    push_check = mocker.patch.object(RdpActionPolicy, "push_check", return_value=expected)

    assert RdpActionPolicy(rdp).start_push_check() == expected
    push_check.assert_called_once_with()


# -------------------------- dedup engine state --------------------------


def test_dedup_engine_state_unavailable() -> None:
    assert DedupEngineState.unavailable() == DedupEngineState(
        status=DedupClientStatus(
            response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
            deduplication_set_status=None,
            findings_count=-1,
        )
    )
    assert str(DedupEngineState.unavailable()) == DedupResponseStatus.STATUS_UNAVAILABLE.value


@pytest.mark.parametrize(
    ("rdp_status", "status_obj", "can_create", "expected_state", "expected_display"),
    [
        (
            Rdp.PushStatus.SUCCESS,
            None,
            True,
            DedupEngineState(),
            "-",
        ),
        (
            Rdp.PushStatus.PENDING,
            None,
            True,
            DedupEngineState(can_create_deduplication_set=True),
            "Ready to start",
        ),
        (
            Rdp.PushStatus.PENDING,
            None,
            False,
            DedupEngineState(can_create_deduplication_set=False),
            "Can't create deduplication set",
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.STATUS_UNAVAILABLE, None, -1),
            False,
            DedupEngineState(
                status=DedupClientStatus(DedupResponseStatus.STATUS_UNAVAILABLE, None, -1),
            ),
            DedupResponseStatus.STATUS_UNAVAILABLE.value,
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.OK, None, -1),
            False,
            DedupEngineState(
                status=DedupClientStatus(DedupResponseStatus.OK, None, -1),
            ),
            "Created / waiting for status",
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 7),
            False,
            DedupEngineState(
                status=DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 7),
            ),
            f"{DeduplicationSetState.READY} / 7 findings",
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, -1),
            False,
            DedupEngineState(
                status=DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, -1),
            ),
            DeduplicationSetState.READY,
        ),
    ],
    ids=[
        "non_pending",
        "ready_to_start",
        "cannot_create",
        "status_unavailable",
        "waiting_for_status",
        "with_findings",
        "without_findings",
    ],
)
def test_dedup_engine_state(
    mocker: MockerFixture,
    rdp,
    rdp_status: str,
    status_obj: DedupClientStatus | None,
    can_create: bool,
    expected_state: DedupEngineState,
    expected_display: str,
) -> None:
    rdp.status = rdp_status
    status_spy = mocker.patch.object(RdpActionPolicy, "deduplication_status", return_value=status_obj)
    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=can_create,
    )

    state = RdpActionPolicy(rdp).dedup_engine_state()

    assert state == expected_state
    assert str(state) == expected_display

    if rdp_status == Rdp.PushStatus.PENDING:
        status_spy.assert_called_once_with(rdp)
    else:
        status_spy.assert_not_called()


def test_dedup_engine_state_remote_error(mocker: MockerFixture, rdp) -> None:
    rdp.status = Rdp.PushStatus.PENDING
    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_status",
        return_value=mocker.MagicMock(
            response_status="SOMETHING",
            deduplication_set_status=None,
            findings_count=-1,
        ),
    )

    state = RdpActionPolicy(rdp).dedup_engine_state()

    assert str(state) == "Remote error"


@pytest.mark.parametrize(
    ("can_create", "expected"),
    [
        (True, DedupEngineState(can_create_deduplication_set=True)),
        (False, None),
    ],
    ids=["can_create", "cannot_create"],
)
def test_dedup_engine_state_handles_stale_remote_error(
    mocker: MockerFixture,
    rdp,
    can_create: bool,
    expected: DedupEngineState | None,
) -> None:
    rdp.status = Rdp.PushStatus.PENDING
    mocker.patch.object(
        RdpActionPolicy,
        "deduplication_status",
        side_effect=RemoteError("not found"),
    )
    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=can_create,
    )

    if expected is None:
        with pytest.raises(RemoteError, match="not found"):
            RdpActionPolicy(rdp).dedup_engine_state()
        return

    state = RdpActionPolicy(rdp).dedup_engine_state()

    assert state == expected
    assert str(state) == "Ready to start"


# ----------------------------- policy cache -----------------------------


def test_get_rdp_policy_caches_policy_on_rdp(rdp) -> None:
    rdp._rdp_policy = None

    policy = get_rdp_policy(rdp)

    assert isinstance(policy, RdpActionPolicy)
    assert policy.rdp is rdp
    assert rdp._rdp_policy is policy
    assert get_rdp_policy(rdp) is policy


def test_get_rdp_policy_reuses_existing_policy(mocker: MockerFixture, rdp) -> None:
    policy = mocker.MagicMock()
    rdp._rdp_policy = policy

    assert get_rdp_policy(rdp) is policy
