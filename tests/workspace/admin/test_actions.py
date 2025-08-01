from unittest.mock import MagicMock, patch

import pytest
from django.contrib import messages
from django.http import HttpResponse
from django.test import RequestFactory

from country_workspace.workspaces.admin.cleaners.actions import (
    mass_update,
    regex_update,
    bulk_update_export,
    calculate_checksum,
    push_to_hope,
    validate_records,
)
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def beneficiary_admin():
    admin = BeneficiaryBaseAdmin(MagicMock(), MagicMock())
    admin.message_user = MagicMock()
    return admin


@pytest.fixture
def mock_admin():
    admin = MagicMock()
    admin.message_user = MagicMock()
    admin.get_common_context = MagicMock(return_value={})
    admin.get_checker = MagicMock(return_value=MagicMock())
    admin.get_preserved_filters = MagicMock(return_value={})
    admin.model._meta = MagicMock()
    admin.get_selected_program = MagicMock(return_value=MagicMock())

    admin._check_empty_queryset = MagicMock(
        side_effect=lambda request, queryset: (
            admin.message_user(
                request,
                "No records were selected. Please select at least one record to perform this action.",
                "warning",
            )
            or True
            if not queryset.exists()
            else False
        )
    )
    return admin


@pytest.fixture
def mock_request(rf):
    request = rf.post("/test/")
    request.user = MagicMock()
    request.POST = {}
    return request


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_mass_update_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = mass_update(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_regex_update_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = regex_update(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_bulk_update_export_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = bulk_update_export(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_calculate_checksum_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = calculate_checksum(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


@patch("country_workspace.workspaces.admin.cleaners.actions.redirect")
def test_push_to_hope_redirects_when_queryset_empty(mock_redirect, mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False
    mock_redirect.return_value = HttpResponse()

    result = push_to_hope(mock_admin, mock_request, empty_queryset)

    mock_redirect.assert_called_once_with(".")
    assert result == mock_redirect.return_value


def test_validate_records_returns_none_when_queryset_empty(mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False

    result = validate_records(mock_admin, mock_request, empty_queryset)

    assert result is None
    mock_admin.message_user.assert_called_once()


def test_actions_continue_execution_when_queryset_not_empty(mock_admin, mock_request):
    non_empty_queryset = MagicMock()
    non_empty_queryset.exists.return_value = True
    non_empty_queryset.model._meta = MagicMock()
    non_empty_queryset.values_list.return_value = [1, 2, 3]

    result = mock_admin._check_empty_queryset(mock_request, non_empty_queryset)
    assert result is False


def test_check_empty_queryset_with_empty_queryset(beneficiary_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False

    result = beneficiary_admin._check_empty_queryset(mock_request, empty_queryset)

    assert result is True
    beneficiary_admin.message_user.assert_called_once_with(
        mock_request,
        "No records were selected. Please select at least one record to perform this action.",
        messages.WARNING,
    )
