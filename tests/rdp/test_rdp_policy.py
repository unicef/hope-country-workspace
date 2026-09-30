import pytest

from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck, RdpActionPolicy, get_rdp_policy


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("allowed", [True, False])
def test_action_check_require(allowed: bool) -> None:
    check = ActionCheck(allowed, "blocked")

    if allowed:
        check.require()
    else:
        with pytest.raises(RdpWorkflowError, match="blocked"):
            check.require()


@pytest.mark.parametrize(
    ("status", "operation_status", "allowed"),
    [
        (Rdp.PushStatus.PENDING, None, True),
        (Rdp.PushStatus.FAILURE, None, True),
        (Rdp.PushStatus.REVIEW_PENDING, None, True),
        (Rdp.PushStatus.SUCCESS, None, False),
        (Rdp.PushStatus.PENDING, RdpOperation.Status.PENDING, False),
        (Rdp.PushStatus.PENDING, RdpOperation.Status.SUCCESS, True),
    ],
)
def test_cancel_check(
    rdp: Rdp,
    status: Rdp.PushStatus,
    operation_status: RdpOperation.Status | None,
    allowed: bool,
) -> None:
    from testutils.factories import BiometricRdpOperationFactory

    rdp.status = status
    rdp.save(update_fields=["status"])
    if operation_status is not None:
        BiometricRdpOperationFactory(rdp=rdp, status=operation_status)

    assert RdpActionPolicy(rdp).cancel_check().allowed is allowed


def test_reset_check_rejects_non_successful_rdp(rdp: Rdp) -> None:
    assert RdpActionPolicy(rdp).reset_check().allowed is False


def test_reset_check_allows_latest_successful_rdp(successful_rdp: Rdp) -> None:
    assert RdpActionPolicy(successful_rdp).reset_check().allowed is True


def test_reset_check_rejects_when_newer_successful_rdp_exists(successful_rdp: Rdp) -> None:
    from testutils.factories import RdpFactory

    RdpFactory(program=successful_rdp.program, status=Rdp.PushStatus.SUCCESS)

    assert RdpActionPolicy(successful_rdp).reset_check().allowed is False


def test_get_rdp_policy_is_cached(rdp: Rdp) -> None:
    assert get_rdp_policy(rdp) is get_rdp_policy(rdp)
