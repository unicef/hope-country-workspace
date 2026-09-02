from uuid import uuid4

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DedupClientStatus, DedupResponseStatus, DeduplicationSetState
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.deduplication.constants import DEDUP_CALLBACK_SALT
from country_workspace.rdp.deduplication.workflow import (
    _build_dedup_callback_url,
    _handle_deduplicated,
    _lock_and_fail_rdp,
    claim_rdp_deduplication,
    create_and_push_rdp_core,
    create_rdp_and_start_dedup_core,
    dedup_callback_handle,
    dedup_existing_rdp_core,
)
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.types import RdpWorkflowOutcome

MOD = "country_workspace.rdp.deduplication.workflow"

pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(mocker: MockerFixture):
    return mocker.MagicMock(
        pk=7,
        status=Rdp.PushStatus.DEDUP_PENDING,
        deduplication_set_id=uuid4(),
        is_dedup_settings_locked=False,
        hope_rdi_id="OLD-RDI",
        pushed_by=mocker.MagicMock(),
        program=mocker.MagicMock(unicef_id="PROGRAM"),
    )


@pytest.fixture
def job(mocker: MockerFixture, rdp):
    return mocker.MagicMock(pk=11, config={"rdp_id": 7}, program=rdp.program)


@pytest.fixture
def deduplicated_setup(rdp, mocker: MockerFixture):
    origin_job = mocker.MagicMock(config={"max_dedup_findings_percent": 20})
    get_job = mocker.patch.object(AsyncJob.objects, "get", return_value=origin_job)

    qs = mocker.MagicMock()
    qs.count.return_value = 10
    mocker.patch(f"{MOD}.qs_individuals_for_rdp", return_value=qs)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)

    attempt_id = uuid4()
    rdp.start_push_attempt.return_value = attempt_id
    start = rdp.start_push_attempt

    push_job = mocker.MagicMock(pk=22)
    create = mocker.patch.object(AsyncJob.objects, "create", return_value=push_job)

    fail = mocker.patch(f"{MOD}._lock_and_fail_rdp")
    fail_pending = mocker.patch(f"{MOD}._fail_pending_push")
    mocker.patch(f"{MOD}.fqn", return_value="push-action")

    return {
        "origin_job": origin_job,
        "get_job": get_job,
        "qs": qs,
        "attempt_id": attempt_id,
        "start": start,
        "push_job": push_job,
        "create": create,
        "fail": fail,
        "fail_pending": fail_pending,
    }


@override_config(APP_BASE_URL="https://cw.example.org/")
def test_build_dedup_callback_url(mocker: MockerFixture) -> None:
    dumps = mocker.patch(f"{MOD}.signing.dumps", return_value="token")
    mocker.patch(f"{MOD}.reverse", return_value="/callback/token/")

    assert _build_dedup_callback_url(7, 11) == "https://cw.example.org/callback/token/"
    dumps.assert_called_once_with({"rdp_id": 7, "job_id": 11}, salt=DEDUP_CALLBACK_SALT)


@pytest.mark.parametrize(
    "case",
    [
        ("policy_denied", False),
        ("status_changed", False),
        ("locked", False),
        ("new_set", True),
        ("existing_set", True),
    ],
    ids=["policy_denied", "status_changed", "locked", "new_set", "existing_set"],
)
def test_claim_rdp_deduplication(rdp, mocker: MockerFixture, case) -> None:
    scenario, expected = case
    policy = mocker.MagicMock(can_create_deduplication_set=scenario == "new_set")
    policy.claim_deduplication_check.return_value = ActionCheck(scenario != "policy_denied")

    if scenario == "status_changed":
        rdp.status = Rdp.PushStatus.SUCCESS
    elif scenario == "locked":
        rdp.status = Rdp.PushStatus.PENDING
        rdp.is_dedup_settings_locked = True
    else:
        rdp.status = Rdp.PushStatus.PENDING

    if scenario == "new_set":
        rdp.deduplication_set_id = None

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    new_id = uuid4()
    mocker.patch(f"{MOD}.uuid4", return_value=new_id)

    check, result = claim_rdp_deduplication(7)

    assert check.allowed is expected
    assert (result is rdp) is expected

    if scenario == "policy_denied":
        lock.assert_not_called()
    elif expected:
        fields = ["is_dedup_settings_locked"]
        if scenario == "new_set":
            assert rdp.deduplication_set_id == new_id
            fields.append("deduplication_set_id")
        rdp.save.assert_called_once_with(update_fields=fields)
    else:
        rdp.save.assert_not_called()


@pytest.mark.parametrize(
    "case",
    ["claim_error", "processor_error", "success"],
    ids=["claim_error", "processor_error", "success"],
)
def test_create_rdp_and_start_dedup(job, rdp, mocker: MockerFixture, case: str) -> None:
    create_result = {"rdp_id": 7}
    mocker.patch(f"{MOD}.create_rdp_core", return_value=create_result)
    claim = mocker.patch(f"{MOD}.claim_rdp_deduplication", return_value=(ActionCheck(True), rdp))
    mocker.patch(f"{MOD}._build_dedup_callback_url", return_value="https://cw/callback/")

    processor = mocker.MagicMock(has_errors=case == "processor_error", total={"errors": ["boom"]})
    mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)

    locked = mocker.MagicMock()
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    if case == "claim_error":
        claim.return_value = ActionCheck(False), None

    if case == "success":
        result = create_rdp_and_start_dedup_core(job)

        assert result == {
            **create_result,
            "workflow_outcome": RdpWorkflowOutcome.AWAITING_DEDUP_CALLBACK,
        }
        locked.mark_deduplication_pending.assert_called_once_with()
        release.assert_not_called()
    else:
        with pytest.raises(RdpWorkflowError):
            create_rdp_and_start_dedup_core(job)

        assert release.called is (case == "processor_error")
        if case == "processor_error":
            locked.mark_deduplication_failed.assert_called_once_with()


@pytest.mark.parametrize("has_errors", [False, True], ids=["success", "processor_error"])
def test_dedup_existing_rdp(job, rdp, mocker: MockerFixture, has_errors: bool) -> None:
    client = mocker.MagicMock()
    client.get_deduplication_set_group_config.return_value = {"threshold": 10}
    context = mocker.MagicMock()
    context.__enter__.return_value = client

    processor = mocker.MagicMock(
        has_errors=has_errors,
        total={"images_sent": 3, "errors": ["boom"] if has_errors else []},
        rdp=rdp,
    )

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=mocker.MagicMock())
    mocker.patch(f"{MOD}.require_policy_check")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=context)
    mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)

    locked = mocker.MagicMock()
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    append_log = mocker.patch(f"{MOD}.append_rdp_operation_log")
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    if has_errors:
        with pytest.raises(RdpWorkflowError):
            dedup_existing_rdp_core(job)
    else:
        assert dedup_existing_rdp_core(job) == {"rdp_id": 7, "images_sent": 3}

    append_log.assert_called_once_with(
        rdp=locked,
        action=RdpOperationAction.START_DEDUPLICATION,
        result={
            "images_sent": 3,
            "dedup_settings": {"threshold": 10},
            "deduplication_set_id": str(rdp.deduplication_set_id),
        },
    )
    release.assert_called_once_with(rdp_id=7)


@pytest.mark.parametrize(
    "status",
    [Rdp.PushStatus.DEDUP_PENDING, Rdp.PushStatus.SUCCESS],
    ids=["pending", "changed"],
)
def test_lock_and_fail_rdp(rdp, mocker: MockerFixture, status: str) -> None:
    rdp.status = status
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)

    _lock_and_fail_rdp(7, reason="boom")

    if status == Rdp.PushStatus.DEDUP_PENDING:
        rdp.mark_deduplication_failed.assert_called_once_with()
    else:
        rdp.mark_deduplication_failed.assert_not_called()


@pytest.mark.parametrize(
    "case",
    ["missing_job", "no_individuals", "threshold", "status_changed"],
    ids=["missing_job", "no_individuals", "threshold", "status_changed"],
)
def test_handle_deduplicated_stops_before_queue(rdp, deduplicated_setup, case: str) -> None:
    setup = deduplicated_setup

    if case == "missing_job":
        setup["get_job"].side_effect = AsyncJob.DoesNotExist
    elif case == "no_individuals":
        setup["qs"].count.return_value = 0
    elif case == "threshold":
        setup["origin_job"].config["max_dedup_findings_percent"] = 5
    else:
        rdp.status = Rdp.PushStatus.SUCCESS

    _handle_deduplicated(rdp, 7, 11, 1)

    assert setup["fail"].called is (case != "status_changed")
    setup["start"].assert_not_called()
    setup["create"].assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        ("success", None),
        ("existing_rdi", "OLD-RDI"),
        ("create_error", "OLD-RDI"),
        ("queue_error", "OLD-RDI"),
    ],
    ids=["success", "existing_rdi", "create_error", "queue_error"],
)
def test_handle_deduplicated_push(rdp, deduplicated_setup, case) -> None:
    scenario, hope_rdi_id = case
    setup = deduplicated_setup
    rdp.hope_rdi_id = hope_rdi_id

    if scenario == "create_error":
        setup["create"].side_effect = RuntimeError("boom")
    elif scenario == "queue_error":
        setup["push_job"].queue.side_effect = RuntimeError("boom")

    if scenario.endswith("error"):
        with pytest.raises(RuntimeError, match="boom"):
            _handle_deduplicated(rdp, 7, 11, 2)
    else:
        _handle_deduplicated(rdp, 7, 11, 2)

        setup["push_job"].queue.assert_called_once_with()
        assert setup["create"].call_args.kwargs["config"] == {
            "rdp_id": 7,
            "push_attempt_id": str(setup["attempt_id"]),
            "rdi_id_to_reset": hope_rdi_id,
        }

    assert setup["fail"].called is (scenario == "create_error")
    assert setup["fail_pending"].called is (scenario == "queue_error")

    if scenario == "queue_error":
        setup["fail_pending"].assert_called_once_with(
            rdp_id=7,
            push_attempt_id=setup["attempt_id"],
            hope_rdi_id="OLD-RDI",
        )


@pytest.mark.parametrize(
    "case",
    [
        ("not_found", None, "none"),
        ("wrong_status", None, "none"),
        ("missing_set", None, "fail"),
        ("no_status", None, "none"),
        (
            "unavailable",
            DedupClientStatus(DedupResponseStatus.STATUS_UNAVAILABLE, None, -1),
            "none",
        ),
        (
            "failed",
            DedupClientStatus(
                DedupResponseStatus.OK,
                DeduplicationSetState.DEDUPLICATION_FAILED,
                0,
            ),
            "fail",
        ),
        (
            "deduplicated",
            DedupClientStatus(
                DedupResponseStatus.OK,
                DeduplicationSetState.DEDUPLICATED,
                2,
            ),
            "handle",
        ),
        (
            "intermediate",
            DedupClientStatus(DedupResponseStatus.OK, DeduplicationSetState.READY, 0),
            "none",
        ),
    ],
    ids=[
        "not_found",
        "wrong_status",
        "missing_set",
        "no_status",
        "unavailable",
        "failed",
        "deduplicated",
        "intermediate",
    ],
)
def test_dedup_callback_handle(rdp, mocker: MockerFixture, case) -> None:
    scenario, status, expected = case
    get_rdp = mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)

    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = status
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    fail = mocker.patch(f"{MOD}._lock_and_fail_rdp")
    handle = mocker.patch(f"{MOD}._handle_deduplicated")

    if scenario == "not_found":
        get_rdp.side_effect = Rdp.DoesNotExist
    elif scenario == "wrong_status":
        rdp.status = Rdp.PushStatus.PENDING
    elif scenario == "missing_set":
        rdp.deduplication_set_id = None

    dedup_callback_handle(7, 11)

    assert fail.called is (expected == "fail")
    assert handle.called is (expected == "handle")

    if expected == "handle":
        handle.assert_called_once_with(rdp, 7, 11, 2)


@pytest.mark.parametrize(
    "case",
    [(False, False), (True, True)],
    ids=["disabled", "enabled"],
)
def test_create_and_push_rdp(job, mocker: MockerFixture, case) -> None:
    biometric, allowed = case
    job.program = mocker.MagicMock(biometric_deduplication_enabled=biometric)
    flow = mocker.patch(f"{MOD}.create_rdp_and_start_dedup_core", return_value={"rdp_id": 7})

    if allowed:
        assert create_and_push_rdp_core(job) == {"rdp_id": 7}
        flow.assert_called_once_with(job)
    else:
        with pytest.raises(RdpWorkflowError):
            create_and_push_rdp_core(job)
        flow.assert_not_called()
