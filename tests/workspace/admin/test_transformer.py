from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest

from country_workspace.state import state
from country_workspace.workspaces.admin.transformer import CountryTransformerAdmin
from country_workspace.workspaces.models import CountryTransformer


@pytest.fixture
def mock_request():
    request = MagicMock(spec=HttpRequest)
    request.user = MagicMock(spec=User)
    request.user.has_perm.return_value = True
    return request


@pytest.fixture
def mock_tenant():
    tenant = MagicMock()
    tenant.pk = 1
    return tenant


@pytest.fixture
def transformer_admin():
    return CountryTransformerAdmin(model=CountryTransformer, admin_site=MagicMock())


class TestCountryTransformerAdmin:
    def test_get_queryset(self, transformer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        with patch.object(CountryTransformer, "objects") as mock_objects:
            transformer_admin.get_queryset(mock_request)
            mock_objects.filter.assert_called_once_with(office=mock_tenant)

    def test_has_add_permission_success(self, transformer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        mock_request.user.has_perm.return_value = True
        assert transformer_admin.has_add_permission(mock_request) is True
        mock_request.user.has_perm.assert_called_with("country_workspace.add_transformer")

    def test_has_add_permission_no_tenant(self, transformer_admin, mock_request):
        state.tenant = None
        assert transformer_admin.has_add_permission(mock_request) is False

    def test_has_add_permission_no_perm(self, transformer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        mock_request.user.has_perm.return_value = False
        assert transformer_admin.has_add_permission(mock_request) is False

    def test_has_change_permission(self, transformer_admin, mock_request):
        transformer_admin.has_change_permission(mock_request)
        mock_request.user.has_perm.assert_called_with("country_workspace.change_transformer")

    def test_has_delete_permission(self, transformer_admin, mock_request):
        transformer_admin.has_delete_permission(mock_request)
        mock_request.user.has_perm.assert_called_with("country_workspace.delete_transformer")

    def test_has_view_permission(self, transformer_admin, mock_request):
        transformer_admin.has_view_permission(mock_request)
        mock_request.user.has_perm.assert_called_with("country_workspace.view_transformer")

    @patch("country_workspace.workspaces.admin.transformer.WorkspaceModelAdmin.save_model")
    def test_save_model_new(self, mock_super_save, transformer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        obj = MagicMock(spec=CountryTransformer)
        form = MagicMock()
        with patch.object(transformer_admin, "_invalidate_transformer_cache") as mock_invalidate:
            transformer_admin.save_model(mock_request, obj, form, change=False)
            assert obj.office == mock_tenant
            assert obj.created_by == mock_request.user
            mock_super_save.assert_called_once_with(mock_request, obj, form, False)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.transformer.WorkspaceModelAdmin.save_model")
    def test_save_model_existing(self, mock_super_save, transformer_admin, mock_request):
        obj = MagicMock(spec=CountryTransformer)
        form = MagicMock()
        with patch.object(transformer_admin, "_invalidate_transformer_cache") as mock_invalidate:
            transformer_admin.save_model(mock_request, obj, form, change=True)
            mock_super_save.assert_called_once_with(mock_request, obj, form, True)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.transformer.WorkspaceModelAdmin.delete_model")
    def test_delete_model(self, mock_super_delete, transformer_admin, mock_request):
        obj = MagicMock(spec=CountryTransformer)
        with patch.object(transformer_admin, "_invalidate_transformer_cache") as mock_invalidate:
            transformer_admin.delete_model(mock_request, obj)
            mock_super_delete.assert_called_once_with(mock_request, obj)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.transformer.WorkspaceModelAdmin.delete_queryset")
    def test_delete_queryset(self, mock_super_delete, transformer_admin, mock_request):
        queryset = MagicMock()
        with patch.object(transformer_admin, "_invalidate_transformer_cache") as mock_invalidate:
            transformer_admin.delete_queryset(mock_request, queryset)
            mock_super_delete.assert_called_once_with(mock_request, queryset)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.transformer.cache")
    def test_invalidate_transformer_cache_with_tenant(self, mock_cache, transformer_admin, mock_tenant):
        state.tenant = mock_tenant
        transformer_admin._invalidate_transformer_cache()
        mock_cache.delete.assert_called_once_with(f"transformer_list:{mock_tenant.pk}")

    @patch("country_workspace.workspaces.admin.transformer.cache")
    def test_invalidate_transformer_cache_no_tenant(self, mock_cache, transformer_admin):
        state.tenant = None
        transformer_admin._invalidate_transformer_cache()
        mock_cache.delete.assert_not_called()
