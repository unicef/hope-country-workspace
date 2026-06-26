import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    DedupClientStatus,
    DedupResponseStatus,
    DeduplicationSetState,
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    PUSHABLE_DEDUPLICATION_SET_STATES,
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
        parent_id=None,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id="ds-1",
        program=program,
    )
    rdp.PushStatus = Rdp.PushStatus
    return rdp


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


def test_policy_owner(mocker: MockerFixture, rdp) -> None:
    owner = mocker.MagicMock()
    spy = mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)
    assert RdpActionPolicy(rdp).owner is owner
    spy.assert_called_once_with(rdp=rdp)


@pytest.mark.parametrize(
    ("source_set_id", "owner_set_id", "expected"),
    [
        ("ds-source", "ds-owner", "source"),
        ("", "ds-owner", "owner"),
        ("", "", None),
    ],
    ids=["source_first", "owner_fallback", "missing"],
)
def test_clone_deduplication_source(
    mocker: MockerFixture,
    rdp,
    source_set_id: str,
    owner_set_id: str,
    expected: str | None,
) -> None:
    owner = mocker.MagicMock(deduplication_set_id=owner_set_id)
    rdp.deduplication_set_id = source_set_id
    mocker.patch.object(RdpActionPolicy, "owner", new_callable=mocker.PropertyMock, return_value=owner)
    result = RdpActionPolicy(rdp).clone_deduplication_source()
    assert result is {"source": rdp, "owner": owner, None: None}[expected]


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


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "expected"),
    [
        (Rdp.PushStatus.PENDING, True, "ds-1", (True, True, True, True)),
        (Rdp.PushStatus.PENDING, True, "", (True, False, True, True)),
        (Rdp.PushStatus.PENDING, False, "ds-1", (False, False, False, True)),
        (Rdp.PushStatus.PUSHED, True, "ds-1", (False, False, True, False)),
    ],
    ids=["pending_with_set", "pending_without_set", "pending_disabled", "non_pending"],
)
def test_visibility_methods(
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    expected: tuple[bool, bool, bool, bool],
) -> None:
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled
    rdp.deduplication_set_id = set_id
    policy = RdpActionPolicy(rdp)

    assert (
        policy.is_deduplicate_visible(),
        policy.is_reject_ds_visible(),
        policy.is_clone_visible(),
        policy.is_push_visible(),
    ) == expected


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "can_create", "expected"),
    [
        (
            Rdp.PushStatus.PUSHED,
            True,
            "ds-1",
            DeduplicationSetState.READY,
            True,
            ActionCheck(False, f"RDP: can not run dedup in status={Rdp.PushStatus.PUSHED}"),
        ),
        (
            Rdp.PushStatus.PENDING,
            False,
            "ds-1",
            DeduplicationSetState.READY,
            True,
            ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program."),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            None,
            False,
            ActionCheck(False, "DedupEngine: can not create deduplication set for this program."),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            None,
            True,
            ActionCheck(True),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            DeduplicationSetState.APPROVED,
            True,
            ActionCheck(True),
        ),
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                False,
                ActionCheck(True),
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
                ActionCheck(
                    False,
                    f"DedupEngine: can not process deduplication set in state={state!r}.",
                ),
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
    expected: ActionCheck,
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

    assert RdpActionPolicy(rdp).deduplicate_check() == expected


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "expected"),
    [
        (
            Rdp.PushStatus.PUSHED,
            True,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(False, f"RDP: can not reject deduplication set in status={Rdp.PushStatus.PUSHED}"),
        ),
        (
            Rdp.PushStatus.PENDING,
            False,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program."),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP."),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            DeduplicationSetState.READY,
            ActionCheck(
                False,
                f"DedupEngine: can not reject deduplication set in state={DeduplicationSetState.READY!r}.",
            ),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(True),
        ),
    ],
    ids=["not_pending", "disabled", "missing_set_id", "wrong_state", "ok"],
)
def test_reject_ds_check(
    mocker: MockerFixture,
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    state: str,
    expected: ActionCheck,
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

    assert RdpActionPolicy(rdp).reject_ds_check() == expected


@pytest.mark.parametrize(
    ("status", "enabled", "has_pending", "dedup_check", "expected"),
    [
        (
            Rdp.PushStatus.PENDING,
            False,
            False,
            ActionCheck(True),
            ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program."),
        ),
        (
            Rdp.PushStatus.PUSHED,
            True,
            False,
            ActionCheck(True),
            ActionCheck(False, f"RDP: can not clone in status={Rdp.PushStatus.PUSHED}"),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            True,
            ActionCheck(True),
            ActionCheck(False, "RDP: can not clone while another RDP is pending"),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            False,
            ActionCheck(False, "blocked"),
            ActionCheck(False, "blocked"),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            False,
            ActionCheck(True),
            ActionCheck(True),
        ),
    ],
    ids=["disabled", "pushed", "other_pending", "dedup_blocked", "ok"],
)
def test_clone_check(
    mocker: MockerFixture,
    rdp,
    status: str,
    enabled: bool,
    has_pending: bool,
    dedup_check: ActionCheck,
    expected: ActionCheck,
) -> None:
    owner = mocker.MagicMock()
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled

    mocker.patch.object(RdpActionPolicy, "owner", new_callable=mocker.PropertyMock, return_value=owner)
    pending = mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=has_pending)
    dedup = mocker.patch.object(RdpActionPolicy, "_clone_deduplication_check", return_value=dedup_check)

    assert RdpActionPolicy(rdp).clone_check() == expected

    if enabled and status not in [Rdp.PushStatus.PUSHED, Rdp.PushStatus.MERGED]:
        pending.assert_called_once_with(owner=owner, exclude_ids=(1,))
    else:
        pending.assert_not_called()

    if enabled and status not in [Rdp.PushStatus.PUSHED, Rdp.PushStatus.MERGED] and not has_pending:
        dedup.assert_called_once_with()
    else:
        dedup.assert_not_called()


@pytest.mark.parametrize(
    ("source_exists", "status", "expected"),
    [
        (False, None, ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")),
        (True, None, ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP.")),
        (
            True,
            DedupClientStatus(DedupResponseStatus.STATUS_UNAVAILABLE, None, -1),
            ActionCheck(False, "DedupEngine: can not retrieve deduplication set status."),
        ),
        (
            True,
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 0),
            ActionCheck(
                False,
                f"DedupEngine: can not clone RDP for deduplication set in state={DeduplicationSetState.READY!r}.",
            ),
        ),
        (
            True,
            DedupClientStatus(DedupResponseStatus.OK, CLONEABLE_DEDUPLICATION_SET_STATES[0], 0),
            ActionCheck(True),
        ),
    ],
    ids=["missing_source", "missing_status", "unavailable", "not_cloneable", "ok"],
)
def test_clone_deduplication_check(
    mocker: MockerFixture,
    rdp,
    source_exists: bool,
    status: DedupClientStatus | None,
    expected: ActionCheck,
) -> None:
    source = rdp if source_exists else None
    mocker.patch.object(RdpActionPolicy, "clone_deduplication_source", return_value=source)
    status_spy = mocker.patch.object(RdpActionPolicy, "deduplication_status", return_value=status)

    assert RdpActionPolicy(rdp)._clone_deduplication_check() == expected

    if source_exists:
        status_spy.assert_called_once_with(rdp)
    else:
        status_spy.assert_not_called()


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "expected"),
    [
        (
            Rdp.PushStatus.PUSHED,
            True,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(False, f"RDP: can not push in status={Rdp.PushStatus.PUSHED}"),
        ),
        (
            Rdp.PushStatus.PENDING,
            False,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(True),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP."),
        ),
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                ActionCheck(True),
            )
            for state in PUSHABLE_DEDUPLICATION_SET_STATES
        ],
        *[
            (
                Rdp.PushStatus.PENDING,
                True,
                "ds-1",
                state,
                ActionCheck(
                    False,
                    f"DedupEngine: can not push with deduplication set in state={state!r}.",
                ),
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
    expected: ActionCheck,
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

    assert RdpActionPolicy(rdp).push_check() == expected


def test_claim_deduplication_check_blocks_locked_active_dedup(
    mocker: MockerFixture,
    rdp,
) -> None:
    rdp.is_dedup_settings_locked = True
    deduplicate_check = mocker.patch.object(RdpActionPolicy, "deduplicate_check")

    check = RdpActionPolicy(rdp).claim_deduplication_check()

    assert check.allowed is False
    assert "already been started" in check.reason
    deduplicate_check.assert_not_called()


@pytest.mark.parametrize(
    "can_create",
    [False, True],
    ids=["cannot_create", "can_create"],
)
def test_claim_deduplication_check_delegates_to_deduplicate_check(
    mocker: MockerFixture,
    rdp,
    can_create: bool,
) -> None:
    expected = ActionCheck(True)
    rdp.is_dedup_settings_locked = False

    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=can_create,
    )
    deduplicate_check = mocker.patch.object(
        RdpActionPolicy,
        "deduplicate_check",
        return_value=expected,
    )

    assert RdpActionPolicy(rdp).claim_deduplication_check() == expected
    deduplicate_check.assert_called_once_with()


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
            Rdp.PushStatus.PUSHED,
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
