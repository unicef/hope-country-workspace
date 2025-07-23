from unittest.mock import MagicMock

import pytest
from django.test import RequestFactory

from country_workspace.workspaces.admin.cleaners.actions import _check_empty_queryset


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_admin():
    admin = MagicMock()
    admin.message_user = MagicMock()
    return admin


@pytest.fixture
def mock_request(rf):
    request = rf.post("/test/")
    request.user = MagicMock()
    return request


def test_check_empty_queryset_with_empty_queryset(mock_admin, mock_request):
    empty_queryset = MagicMock()
    empty_queryset.exists.return_value = False

    result = _check_empty_queryset(mock_admin, mock_request, empty_queryset)

    assert result is True
    mock_admin.message_user.assert_called_once()


def test_check_empty_queryset_with_non_empty_queryset(mock_admin, mock_request):
    non_empty_queryset = MagicMock()
    non_empty_queryset.exists.return_value = True

    result = _check_empty_queryset(mock_admin, mock_request, non_empty_queryset)

    assert result is False
    mock_admin.message_user.assert_not_called()
