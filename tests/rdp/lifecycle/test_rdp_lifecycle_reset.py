import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp
from country_workspace.rdp.lifecycle import reset
from country_workspace.rdp.policy import ActionCheck


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("allowed", [False, True])
def test_reset_rdp(
    successful_rdp: Rdp,
    mocker: MockerFixture,
    allowed: bool,
) -> None:
    mocker.patch.object(reset, "lock_rdp_for_update", return_value=successful_rdp)
    policy = mocker.patch.object(reset, "get_rdp_policy").return_value
    policy.reset_check.return_value = check = ActionCheck(allowed, "blocked" if not allowed else None)
    removed = mocker.patch.object(reset, "set_rdp_beneficiaries_removed")
    cancel = mocker.patch.object(successful_rdp, "mark_cancelled")

    assert reset.reset_rdp(rdp_id=successful_rdp.pk) == (ActionCheck(True) if allowed else check)

    if allowed:
        removed.assert_called_once_with(rdp=successful_rdp, removed=False)
        cancel.assert_called_once_with()
    else:
        removed.assert_not_called()
        cancel.assert_not_called()
