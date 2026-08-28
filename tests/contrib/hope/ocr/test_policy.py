import pytest

from country_workspace.contrib.hope.ocr.policy import OcrActionPolicy, get_ocr_policy
from country_workspace.models import OcrRun, Rdp

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "status",
    [Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE],
)
def test_is_open_true_for_open_statuses(rdp, status):
    rdp.status = status
    assert OcrActionPolicy(rdp).is_open is True


@pytest.mark.parametrize(
    "status",
    [Rdp.PushStatus.SUCCESS, Rdp.PushStatus.CANCELLED, Rdp.PushStatus.DEDUP_PENDING],
)
def test_is_open_false_for_closed_statuses(rdp, status):
    rdp.status = status
    assert OcrActionPolicy(rdp).is_open is False


def test_has_ocr_run(rdp):
    policy = OcrActionPolicy(rdp)
    assert policy.has_ocr_run is False

    OcrRun.objects.create(rdp=rdp)

    assert policy.has_ocr_run is True


def test_ocr_check_allowed_when_open_and_no_run(rdp):
    check = OcrActionPolicy(rdp).ocr_check()
    assert check.allowed is True


def test_ocr_check_blocked_when_not_open(rdp):
    rdp.status = Rdp.PushStatus.SUCCESS
    check = OcrActionPolicy(rdp).ocr_check()
    assert check.allowed is False
    assert "status=" in check.reason


def test_ocr_check_blocked_when_run_exists(rdp):
    OcrRun.objects.create(rdp=rdp)
    check = OcrActionPolicy(rdp).ocr_check()
    assert check.allowed is False
    assert "already" in check.reason


def test_is_ocr_visible_matches_is_open(rdp):
    policy = OcrActionPolicy(rdp)
    assert policy.is_ocr_visible() is True

    rdp.status = Rdp.PushStatus.CANCELLED
    assert policy.is_ocr_visible() is False


def test_get_ocr_policy_caches_instance_on_rdp(rdp):
    policy1 = get_ocr_policy(rdp)
    policy2 = get_ocr_policy(rdp)
    assert policy1 is policy2
