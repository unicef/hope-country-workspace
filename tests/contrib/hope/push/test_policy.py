import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.contrib.dedup_engine.deduplication_status import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    DedupClientStatus,
    DedupResponseStatus,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.push.policy import (
    ActionCheck,
    RdpActionPolicy,
    get_rdp_policy,
)
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

    spy.assert_called_once_with("program-1", "ds-1")


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
        (Rdp.PushStatus.SUCCESS, True, "ds-1", (False, False, True, False)),
    ],
    ids=["pending_with_set", "pending_without_set", "pending_disabled", "non_pending"],
)
def test_visible_methods(
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
        policy.visible_deduplicate(),
        policy.visible_reject_ds(),
        policy.visible_clone(),
        policy.visible_push(),
    ) == expected


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "can_create", "expected"),
    [
        (
            Rdp.PushStatus.SUCCESS,
            True,
            "ds-1",
            DeduplicationSetState.READY,
            True,
            ActionCheck(False, f"RDP: can not run dedup in status={Rdp.PushStatus.SUCCESS}"),
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
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            True,
            ActionCheck(False, "DedupEngine: can not run dedup for a deduplicated set."),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            DeduplicationSetState.READY,
            True,
            ActionCheck(True),
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
    ],
    ids=["not_pending", "disabled", "already_deduplicated", "existing_set_ok", "cannot_create", "can_create"],
)
def test_can_deduplicate(
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

    assert RdpActionPolicy(rdp).can_deduplicate() == expected


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "state", "expected"),
    [
        (
            Rdp.PushStatus.SUCCESS,
            True,
            "ds-1",
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(False, f"RDP: can not reject deduplication set in status={Rdp.PushStatus.SUCCESS}"),
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
def test_can_reject_ds(
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

    assert RdpActionPolicy(rdp).can_reject_ds() == expected


@pytest.mark.parametrize(
    (
        "rdp_status",
        "enabled",
        "has_pending",
        "dedup_status",
        "expected",
        "exclude_ids",
        "pending_called",
        "status_called",
    ),
    [
        (
            Rdp.PushStatus.PENDING,
            False,
            False,
            None,
            ActionCheck(False, "DedupEngine: biometric deduplication is not enabled for this program."),
            (1,),
            False,
            False,
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            True,
            None,
            ActionCheck(False, "RDP: can not clone while another RDP is pending"),
            (1,),
            True,
            False,
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            False,
            None,
            ActionCheck(False, "DedupEngine: deduplication_set_id is not set for this RDP."),
            (1,),
            True,
            True,
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            False,
            DedupClientStatus(DedupResponseStatus.STATUS_UNAVAILABLE, None, -1),
            ActionCheck(False, "DedupEngine: can not retrieve deduplication set status."),
            (1,),
            True,
            True,
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            False,
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 0),
            ActionCheck(
                False,
                f"DedupEngine: can not clone RDP for deduplication set in state={DeduplicationSetState.READY!r}.",
            ),
            (1,),
            True,
            True,
        ),
        (
            Rdp.PushStatus.SUCCESS,
            True,
            False,
            DedupClientStatus(DedupResponseStatus.OK, CLONEABLE_DEDUPLICATION_SET_STATES[0], 0),
            ActionCheck(True),
            (),
            True,
            True,
        ),
    ],
    ids=["disabled", "other_pending", "missing_status", "status_unavailable", "state_not_cloneable", "ok"],
)
def test_can_clone(
    mocker: MockerFixture,
    rdp,
    rdp_status: str,
    enabled: bool,
    has_pending: bool,
    dedup_status: DedupClientStatus | None,
    expected: ActionCheck,
    exclude_ids: tuple[int, ...],
    pending_called: bool,
    status_called: bool,
) -> None:
    owner = mocker.MagicMock()
    rdp.status = rdp_status
    rdp.program.biometric_deduplication_enabled = enabled

    mocker.patch.object(RdpActionPolicy, "owner", new_callable=mocker.PropertyMock, return_value=owner)
    pending_spy = mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=has_pending)
    status_spy = mocker.patch.object(RdpActionPolicy, "deduplication_status", return_value=dedup_status)

    assert RdpActionPolicy(rdp).can_clone() == expected

    if pending_called:
        pending_spy.assert_called_once_with(owner=owner, exclude_ids=exclude_ids)
    else:
        pending_spy.assert_not_called()

    if status_called:
        status_spy.assert_called_once_with(owner)
    else:
        status_spy.assert_not_called()


@pytest.mark.parametrize(
    ("status", "enabled", "set_id", "can_create", "state", "expected"),
    [
        (
            Rdp.PushStatus.SUCCESS,
            True,
            "ds-1",
            False,
            DeduplicationSetState.READY,
            ActionCheck(False, f"RDP: can not push in status={Rdp.PushStatus.SUCCESS}"),
        ),
        (
            Rdp.PushStatus.PENDING,
            False,
            "ds-1",
            False,
            DeduplicationSetState.READY,
            ActionCheck(True),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "",
            False,
            DeduplicationSetState.READY,
            ActionCheck(True),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            True,
            DeduplicationSetState.READY,
            ActionCheck(True),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            False,
            DeduplicationSetState.DEDUPLICATED,
            ActionCheck(True),
        ),
        (
            Rdp.PushStatus.PENDING,
            True,
            "ds-1",
            False,
            DeduplicationSetState.READY,
            ActionCheck(
                False,
                f"DedupEngine: can not push with deduplication set in state={DeduplicationSetState.READY!r}.",
            ),
        ),
    ],
    ids=["not_pending", "disabled", "missing_set_id", "can_create", "deduplicated", "blocked_state"],
)
def test_can_push(
    mocker: MockerFixture,
    rdp,
    status: str,
    enabled: bool,
    set_id: str,
    can_create: bool,
    state: str,
    expected: ActionCheck,
) -> None:
    rdp.status = status
    rdp.program.biometric_deduplication_enabled = enabled
    rdp.deduplication_set_id = set_id

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

    assert RdpActionPolicy(rdp).can_push() == expected


@pytest.mark.parametrize(
    ("rdp_status", "status_obj", "can_create", "expected"),
    [
        (Rdp.PushStatus.SUCCESS, None, True, "-"),
        (Rdp.PushStatus.PENDING, None, True, "Ready to start"),
        (Rdp.PushStatus.PENDING, None, False, "Can't create deduplication set"),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.STATUS_UNAVAILABLE, None, -1),
            False,
            DedupResponseStatus.STATUS_UNAVAILABLE.value,
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.OK, None, -1),
            False,
            "Created / waiting for status",
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 7),
            False,
            f"{DeduplicationSetState.READY} / 7 findings",
        ),
        (
            Rdp.PushStatus.PENDING,
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, -1),
            False,
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
    expected: str,
) -> None:
    rdp.status = rdp_status
    status_spy = mocker.patch.object(RdpActionPolicy, "deduplication_status", return_value=status_obj)
    mocker.patch.object(
        RdpActionPolicy,
        "can_create_deduplication_set",
        new_callable=mocker.PropertyMock,
        return_value=can_create,
    )

    assert RdpActionPolicy(rdp).dedup_engine_state() == expected

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

    assert RdpActionPolicy(rdp).dedup_engine_state() == "Remote error"


def test_get_rdp_policy_caches_on_rdp(rdp) -> None:
    policy1 = get_rdp_policy(rdp)
    policy2 = get_rdp_policy(rdp)

    assert policy1 is policy2
    assert rdp._rdp_policy is policy1
