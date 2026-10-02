from decimal import Decimal
from typing import cast

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp
from country_workspace.rdp.deduplication.types import ThresholdType
from country_workspace.rdp.push.policy import PushPolicy, get_push_policy, threshold_exceeded


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("status", "allowed"),
    [
        (Rdp.PushStatus.REVIEW_PENDING, True),
        (Rdp.PushStatus.PENDING, False),
    ],
)
def test_review_push_check(rdp: Rdp, status: Rdp.PushStatus, allowed: bool) -> None:
    rdp.status = status

    assert PushPolicy(rdp).review_push_check().allowed is allowed


@pytest.mark.parametrize("incomplete", [True, False])
def test_retry_push_check(
    rdp: Rdp,
    mocker: MockerFixture,
    incomplete: bool,
) -> None:
    from country_workspace.rdp.push import policy as policy_mod

    rdp.status = Rdp.PushStatus.FAILURE
    has_incomplete = mocker.patch.object(policy_mod, "has_incomplete_rdp_operations", return_value=incomplete)

    assert PushPolicy(rdp).retry_push_check().allowed is not incomplete
    has_incomplete.assert_called_once_with(rdp_id=rdp.pk)


def test_retry_push_check_rejects_other_status(rdp: Rdp, mocker: MockerFixture) -> None:
    from country_workspace.rdp.push import policy as policy_mod

    rdp.status = Rdp.PushStatus.PENDING
    has_incomplete = mocker.patch.object(policy_mod, "has_incomplete_rdp_operations")

    assert PushPolicy(rdp).retry_push_check().allowed is False
    has_incomplete.assert_not_called()


def test_get_push_policy_is_cached(rdp: Rdp) -> None:
    assert get_push_policy(rdp) is get_push_policy(rdp)


@pytest.mark.parametrize(
    ("findings_count", "total_count", "threshold_type", "threshold_value", "expected"),
    [
        (2, 10, ThresholdType.COUNT, Decimal(1), True),
        (1, 10, ThresholdType.COUNT, Decimal(1), False),
        (2, 4, ThresholdType.RATE, Decimal(49), True),
        (2, 4, ThresholdType.RATE, Decimal(50), False),
        (15, 10, ThresholdType.RATE, Decimal(120), True),
        (12, 10, ThresholdType.RATE, Decimal(120), False),
    ],
)
def test_threshold_exceeded(
    findings_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
    expected: bool,
) -> None:
    assert (
        threshold_exceeded(
            findings_count=findings_count,
            total_count=total_count,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("findings_count", "total_count", "threshold_type", "threshold_value"),
    [
        (-1, 1, ThresholdType.COUNT, Decimal(0)),
        (0, 0, ThresholdType.COUNT, Decimal(0)),
        (0, 1, ThresholdType.COUNT, Decimal(-1)),
        (0, 1, cast("ThresholdType", "invalid"), Decimal(0)),
    ],
)
def test_threshold_exceeded_rejects_invalid_input(
    findings_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
) -> None:
    with pytest.raises(ValueError, match=r"Invalid"):
        threshold_exceeded(
            findings_count=findings_count,
            total_count=total_count,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
        )
