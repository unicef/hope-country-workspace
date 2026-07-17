"""Tests for the dedup-callback-triggered push flow.

Covers:
- create_rdp_and_start_dedup_core
- create_and_push_rdp_core biometric branching
- dedup_callback_handle (all terminal/intermediate states)
- _build_dedup_callback_url signed token round-trip
"""

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import (
    DedupClientStatus,
    DedupResponseStatus,
    DeduplicationSetState,
)
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.push.orchestration import (
    _build_dedup_callback_url,
    DEDUP_CALLBACK_SALT,
    DEDUP_CALLBACK_MAX_AGE,
    create_and_push_rdp_core,
    create_rdp_and_start_dedup_core,
    dedup_callback_handle,
)
from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.models import AsyncJob, Rdp

MOD = "country_workspace.contrib.hope.push.orchestration"


# ---------------------------------------------------------------------------
# _build_dedup_callback_url
# ---------------------------------------------------------------------------


@override_config(APP_BASE_URL="https://cw.example.org")
def test_build_dedup_callback_url_contains_signed_token() -> None:
    url = _build_dedup_callback_url(rdp_id=7, job_id=42)
    assert url.startswith("https://cw.example.org/api/dedup/callback/")


def test_build_dedup_callback_url_token_verifiable() -> None:
    from django.core import signing

    url = _build_dedup_callback_url(rdp_id=5, job_id=99)
    signed_token = url.rstrip("/").rsplit("/", 1)[-1]
    data = signing.loads(signed_token, salt=DEDUP_CALLBACK_SALT, max_age=DEDUP_CALLBACK_MAX_AGE)
    assert data == {"rdp_id": 5, "job_id": 99}


# ---------------------------------------------------------------------------
# create_rdp_and_start_dedup_core
# ---------------------------------------------------------------------------


def _make_job(mocker: MockerFixture, biometric: bool = True, config: dict | None = None):
    job = mocker.MagicMock()
    job.program.biometric_deduplication_enabled = biometric
    job.config = config or {"pks": [1], "master_detail": False}
    return job


def test_create_rdp_and_start_dedup_core_success(mocker: MockerFixture) -> None:
    job = _make_job(mocker)
    job.pk = 10
    create_result = {"rdp_id": 42, "rdp_str": "RDP-42"}
    rdp = mocker.MagicMock(deduplication_set_id="ds-1", pk=42)

    mocker.patch(f"{MOD}.create_rdp_core", return_value=create_result)
    mocker.patch(f"{MOD}.claim_rdp_deduplication", return_value=(ActionCheck(True), rdp))
    mocker.patch(f"{MOD}._build_dedup_callback_url", return_value="https://cw/callback/token/")
    processor = mocker.MagicMock(has_errors=False)
    mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=mocker.MagicMock())
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    result = create_rdp_and_start_dedup_core(job)

    assert result == {**create_result, "dedup_pending": True}
    processor.run.assert_called_once_with(notification_url="https://cw/callback/token/")
    lock.assert_called_once_with(pk=42)
    release.assert_not_called()


def test_create_rdp_and_start_dedup_core_claim_fails(mocker: MockerFixture, err_contains) -> None:
    job = _make_job(mocker)
    create_result = {"rdp_id": 42, "rdp_str": "RDP-42"}

    mocker.patch(f"{MOD}.create_rdp_core", return_value=create_result)
    mocker.patch(f"{MOD}.claim_rdp_deduplication", return_value=(ActionCheck(False, "denied"), None))
    processor = mocker.patch(f"{MOD}.DedupProcessor")
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    with pytest.raises(HopePushError) as exc:
        create_rdp_and_start_dedup_core(job)

    assert err_contains(exc.value.args[0]["errors"], "could not claim")
    assert exc.value.args[0]["rdp_id"] == 42
    processor.assert_not_called()
    release.assert_not_called()


def test_create_rdp_and_start_dedup_core_processor_errors(mocker: MockerFixture, err_contains) -> None:
    job = _make_job(mocker)
    create_result = {"rdp_id": 42, "rdp_str": "RDP-42"}
    rdp = mocker.MagicMock(pk=42)
    locked = mocker.MagicMock()

    mocker.patch(f"{MOD}.create_rdp_core", return_value=create_result)
    mocker.patch(f"{MOD}.claim_rdp_deduplication", return_value=(ActionCheck(True), rdp))
    mocker.patch(f"{MOD}._build_dedup_callback_url", return_value="https://cw/callback/token/")
    processor = mocker.MagicMock(has_errors=True, total={"errors": ["upload failed"]})
    mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    with pytest.raises(HopePushError) as exc:
        create_rdp_and_start_dedup_core(job)

    assert err_contains(exc.value.args[0]["errors"], "upload failed")
    assert exc.value.args[0]["rdp_id"] == 42
    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")
    release.assert_called_once_with(rdp_id=42)


def test_create_rdp_and_start_dedup_core_sets_dedup_pending_status(mocker: MockerFixture) -> None:
    job = _make_job(mocker)
    job.pk = 10
    create_result = {"rdp_id": 42, "rdp_str": "RDP-42"}
    rdp = mocker.MagicMock(pk=42)
    locked = mocker.MagicMock()

    mocker.patch(f"{MOD}.create_rdp_core", return_value=create_result)
    mocker.patch(f"{MOD}.claim_rdp_deduplication", return_value=(ActionCheck(True), rdp))
    mocker.patch(f"{MOD}._build_dedup_callback_url", return_value="https://cw/callback/token/")
    processor = mocker.MagicMock(has_errors=False)
    mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    create_rdp_and_start_dedup_core(job)

    assert locked.status == Rdp.PushStatus.DEDUP_PENDING
    locked.save.assert_called_once_with(update_fields=["status"])
    release.assert_not_called()


# ---------------------------------------------------------------------------
# create_and_push_rdp_core - biometric branching
# ---------------------------------------------------------------------------


def test_create_and_push_rdp_core_routes_biometric_to_dedup_flow(mocker: MockerFixture) -> None:
    job = _make_job(mocker, biometric=True)
    dedup_flow = mocker.patch(f"{MOD}.create_rdp_and_start_dedup_core", return_value={"dedup_pending": True})

    create_and_push_rdp_core(job)

    dedup_flow.assert_called_once_with(job)


def test_create_and_push_rdp_core_non_biometric_raises(mocker: MockerFixture) -> None:
    job = _make_job(mocker, biometric=False)
    dedup_flow = mocker.patch(f"{MOD}.create_rdp_and_start_dedup_core")

    with pytest.raises(HopePushError):
        create_and_push_rdp_core(job)

    dedup_flow.assert_not_called()


def test_create_and_push_rdp_core_no_program_raises(mocker: MockerFixture) -> None:
    job = mocker.MagicMock()
    job.program = None
    dedup_flow = mocker.patch(f"{MOD}.create_rdp_and_start_dedup_core")

    with pytest.raises(HopePushError):
        create_and_push_rdp_core(job)

    dedup_flow.assert_not_called()


# ---------------------------------------------------------------------------
# dedup_callback_handle
# ---------------------------------------------------------------------------


def _make_rdp(mocker: MockerFixture, *, status=Rdp.PushStatus.DEDUP_PENDING, dedup_set_id="ds-1"):
    rdp = mocker.MagicMock()
    rdp.status = status
    rdp.deduplication_set_id = dedup_set_id
    rdp.pk = 99
    return rdp


def _patch_rdp_for_push(mocker: MockerFixture, rdp=None, *, not_found: bool = False):
    if not_found:
        from country_workspace.models import Rdp as RdpModel

        mocker.patch(f"{MOD}.rdp_for_push", side_effect=RdpModel.DoesNotExist)
    else:
        mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)


def _patch_dedup_status(mocker: MockerFixture, *, state: str, findings_count: int = 0):
    status = DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=state,
        findings_count=findings_count,
    )
    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = status
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    return policy


def _patch_origin_job(mocker: MockerFixture, config: dict | None = None, *, missing: bool = False):
    if missing:
        mocker.patch.object(AsyncJob.objects, "get", side_effect=AsyncJob.DoesNotExist)
        return None
    origin_job = mocker.MagicMock(config=config if config is not None else {})
    mocker.patch.object(AsyncJob.objects, "get", return_value=origin_job)
    return origin_job


def _patch_individuals_count(mocker: MockerFixture, count: int) -> None:
    mocker.patch(
        f"{MOD}.qs_individuals_for_rdp",
        return_value=mocker.MagicMock(count=mocker.MagicMock(return_value=count)),
    )


def test_dedup_callback_handle_rdp_not_found(mocker: MockerFixture) -> None:
    _patch_rdp_for_push(mocker, not_found=True)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    dedup_callback_handle(rdp_id=99, job_id=10)
    set_status.assert_not_called()


def test_dedup_callback_handle_wrong_rdp_status(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker, status=Rdp.PushStatus.PENDING)
    _patch_rdp_for_push(mocker, rdp)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    dedup_callback_handle(rdp_id=99, job_id=10)
    set_status.assert_not_called()


def test_dedup_callback_handle_no_dedup_set_id(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker, dedup_set_id=None)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")


def test_dedup_callback_handle_dedup_engine_unavailable(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker)
    _patch_rdp_for_push(mocker, rdp)
    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = DedupClientStatus(
        response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
        deduplication_set_status=None,
        findings_count=-1,
    )
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_not_called()


def test_dedup_callback_handle_dedup_engine_returns_none_status(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker)
    _patch_rdp_for_push(mocker, rdp)
    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = None
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_not_called()


@pytest.mark.parametrize(
    "failed_state",
    [
        DeduplicationSetState.DEDUPLICATION_FAILED,
        DeduplicationSetState.ENCODING_FAILED,
    ],
    ids=["dedup_failed", "encoding_failed"],
)
def test_dedup_callback_handle_terminal_failure_marks_rdp_failed(
    mocker: MockerFixture, failed_state: DeduplicationSetState
) -> None:
    rdp = _make_rdp(mocker)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=failed_state)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    mocker.patch.object(AsyncJob.objects, "create")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")


@pytest.mark.parametrize(
    "intermediate_state",
    [
        DeduplicationSetState.ENCODING_IN_PROGRESS,
        DeduplicationSetState.ENCODED,
        DeduplicationSetState.DEDUPLICATION_IN_PROGRESS,
        DeduplicationSetState.READY,
    ],
    ids=["encoding_in_progress", "encoded", "dedup_in_progress", "ready"],
)
def test_dedup_callback_handle_intermediate_state_is_noop(
    mocker: MockerFixture, intermediate_state: DeduplicationSetState
) -> None:
    rdp = _make_rdp(mocker)
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=intermediate_state)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_not_called()
    lock.assert_not_called()


def test_dedup_callback_handle_deduplicated_within_threshold_queues_push(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker)
    locked_pending = mocker.MagicMock()
    locked_pending.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=5)
    _patch_origin_job(mocker, {"max_dedup_findings_percent": 10})
    _patch_individuals_count(mocker, 100)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked_pending)
    push_job = mocker.MagicMock()
    create_job = mocker.patch.object(AsyncJob.objects, "create", return_value=push_job)
    on_commit = mocker.patch(f"{MOD}.transaction.on_commit")

    dedup_callback_handle(rdp_id=99, job_id=10)

    AsyncJob.objects.get.assert_called_once_with(pk=10, rdp_id=99)
    create_job.assert_called_once()
    on_commit.assert_called_once_with(push_job.queue)
    assert locked_pending.status == Rdp.PushStatus.PENDING


def test_dedup_callback_handle_deduplicated_skips_push_when_status_changed_under_lock(
    mocker: MockerFixture,
) -> None:
    rdp = _make_rdp(mocker)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.FAILURE
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=5)
    _patch_origin_job(mocker, {"max_dedup_findings_percent": 10})
    _patch_individuals_count(mocker, 100)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    create_job = mocker.patch.object(AsyncJob.objects, "create")
    on_commit = mocker.patch(f"{MOD}.transaction.on_commit")

    dedup_callback_handle(rdp_id=99, job_id=10)

    create_job.assert_not_called()
    on_commit.assert_not_called()
    locked.save.assert_not_called()


def test_dedup_callback_handle_deduplicated_exceeds_threshold_marks_failure(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=20)
    _patch_origin_job(mocker, {"max_dedup_findings_percent": 10})
    _patch_individuals_count(mocker, 100)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    create_job = mocker.patch.object(AsyncJob.objects, "create")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")
    create_job.assert_not_called()


def test_dedup_callback_handle_default_threshold_is_zero(mocker: MockerFixture) -> None:
    """With default threshold=0, any finding should block push."""
    rdp = _make_rdp(mocker)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=1)
    _patch_origin_job(mocker, {})
    _patch_individuals_count(mocker, 100)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")


def test_dedup_callback_handle_zero_findings_within_threshold_queues_push(mocker: MockerFixture) -> None:
    """Zero findings should always be within any threshold including default 0."""
    rdp = _make_rdp(mocker)
    locked_pending = mocker.MagicMock()
    locked_pending.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=0)
    _patch_origin_job(mocker, {})
    _patch_individuals_count(mocker, 100)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked_pending)
    push_job = mocker.MagicMock()
    mocker.patch.object(AsyncJob.objects, "create", return_value=push_job)
    on_commit = mocker.patch(f"{MOD}.transaction.on_commit")

    dedup_callback_handle(rdp_id=99, job_id=10)

    on_commit.assert_called_once_with(push_job.queue)


def test_dedup_callback_handle_missing_origin_job_marks_failure(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=0)
    _patch_origin_job(mocker, missing=True)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    create_job = mocker.patch.object(AsyncJob.objects, "create")

    dedup_callback_handle(rdp_id=99, job_id=10)

    AsyncJob.objects.get.assert_called_once_with(pk=10, rdp_id=99)
    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")
    create_job.assert_not_called()


def test_dedup_callback_handle_zero_individuals_marks_failure(mocker: MockerFixture) -> None:
    rdp = _make_rdp(mocker)
    locked = mocker.MagicMock()
    locked.status = Rdp.PushStatus.DEDUP_PENDING
    _patch_rdp_for_push(mocker, rdp)
    _patch_dedup_status(mocker, state=DeduplicationSetState.DEDUPLICATED, findings_count=0)
    _patch_origin_job(mocker, {"max_dedup_findings_percent": 10})
    _patch_individuals_count(mocker, 0)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    create_job = mocker.patch.object(AsyncJob.objects, "create")

    dedup_callback_handle(rdp_id=99, job_id=10)

    set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="N/A")
    create_job.assert_not_called()
