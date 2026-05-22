from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from country_workspace.state import state
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin


@pytest.fixture
def beneficiary_admin(mocker: MockerFixture) -> BeneficiaryBaseAdmin:
    """A bare ``BeneficiaryBaseAdmin`` instance suitable for unit testing.

    Model and admin_site are mocked because the two methods under test
    don't touch the ORM directly — they only delegate to mixin members.
    """
    admin = BeneficiaryBaseAdmin(MagicMock(), MagicMock())
    admin.message_user = MagicMock()
    return admin


@pytest.fixture
def mock_request(mocker: MockerFixture):
    return mocker.MagicMock(name="request")


def test_import_data_delegates_to_render_with_state_program(
    beneficiary_admin: BeneficiaryBaseAdmin,
    mock_request,
    mocker: MockerFixture,
) -> None:
    program = mocker.MagicMock(name="program")
    state.program = program
    render = mocker.patch.object(beneficiary_admin, "_render_import_data", return_value="rendered")

    result = beneficiary_admin.import_data.func(beneficiary_admin, mock_request)

    render.assert_called_once_with(mock_request, program=program)
    assert result == "rendered"


def test_import_data_uses_current_state_program_at_call_time(
    beneficiary_admin: BeneficiaryBaseAdmin,
    mock_request,
    mocker: MockerFixture,
) -> None:
    """The button must read ``state.program`` lazily (per request)."""
    first_program = mocker.MagicMock(name="first")
    second_program = mocker.MagicMock(name="second")
    render = mocker.patch.object(beneficiary_admin, "_render_import_data", return_value="rendered")

    state.program = first_program
    beneficiary_admin.import_data.func(beneficiary_admin, mock_request)
    state.program = second_program
    beneficiary_admin.import_data.func(beneficiary_admin, mock_request)

    assert [call.kwargs["program"] for call in render.call_args_list] == [
        first_program,
        second_program,
    ]


def test_import_data_propagates_none_program(
    beneficiary_admin: BeneficiaryBaseAdmin,
    mock_request,
    mocker: MockerFixture,
) -> None:
    """No selected program → ``program=None`` is forwarded verbatim.

    The button's ``visible`` predicate normally prevents this path from
    being reachable through the UI, but the method itself must still
    behave predictably (no implicit lookup, no surprise exception).
    """
    state.program = None
    render = mocker.patch.object(beneficiary_admin, "_render_import_data", return_value="rendered")

    beneficiary_admin.import_data.func(beneficiary_admin, mock_request)

    render.assert_called_once_with(mock_request, program=None)


def test_get_import_success_url_returns_changelist_url(
    beneficiary_admin: BeneficiaryBaseAdmin,
    mock_request,
    mocker: MockerFixture,
) -> None:
    program = mocker.MagicMock(name="program")
    get_changelist_url = mocker.patch.object(
        beneficiary_admin, "get_changelist_url", return_value="/workspaces/countryhousehold/"
    )

    url = beneficiary_admin._get_import_success_url(mock_request, program)

    get_changelist_url.assert_called_once_with()
    assert url == "/workspaces/countryhousehold/"


def test_get_import_success_url_ignores_program_argument(
    beneficiary_admin: BeneficiaryBaseAdmin,
    mock_request,
    mocker: MockerFixture,
) -> None:
    """The redirect target depends on the *admin*, not the program.

    Two different programs must still resolve to the same change-list
    URL — that's the whole point of the override.
    """
    mocker.patch.object(beneficiary_admin, "get_changelist_url", return_value="/workspaces/countryhousehold/")

    program_a = mocker.MagicMock()
    program_b = mocker.MagicMock()

    assert beneficiary_admin._get_import_success_url(mock_request, program_a) == (
        beneficiary_admin._get_import_success_url(mock_request, program_b)
    )


def test_get_import_success_url_overrides_mixin_default(
    beneficiary_admin: BeneficiaryBaseAdmin,
    mock_request,
    mocker: MockerFixture,
) -> None:
    """Regression guard: the mixin default redirects to the program
    change page; the ``BeneficiaryBaseAdmin`` override must instead use
    the admin's own change-list URL."""
    program = mocker.MagicMock(name="program")
    mocker.patch.object(beneficiary_admin, "get_changelist_url", return_value="/workspaces/countryhousehold/")
    reverse = mocker.patch("country_workspace.workspaces.admin._import_data.reverse")

    url = beneficiary_admin._get_import_success_url(mock_request, program)

    reverse.assert_not_called()
    assert url == "/workspaces/countryhousehold/"
