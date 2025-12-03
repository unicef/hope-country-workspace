from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest

from country_workspace.state import state
from country_workspace.workspaces.admin.mapping_importer import CountryMappingImporterAdmin
from country_workspace.workspaces.models import CountryMappingImporter, CountryProgram


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
def mapping_importer_admin():
    return CountryMappingImporterAdmin(model=CountryMappingImporter, admin_site=MagicMock())


class TestCountryMappingImporterAdmin:
    def test_get_queryset(self, mapping_importer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        with patch.object(CountryMappingImporter, "objects") as mock_objects:
            mapping_importer_admin.get_queryset(mock_request)
            mock_objects.filter.assert_called_once_with(office=mock_tenant)

    def test_has_add_permission_success(self, mapping_importer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        mock_request.user.has_perm.return_value = True
        assert mapping_importer_admin.has_add_permission(mock_request) is True
        mock_request.user.has_perm.assert_called_with("country_workspace.add_mappingimporter")

    def test_has_add_permission_no_tenant(self, mapping_importer_admin, mock_request):
        state.tenant = None
        assert mapping_importer_admin.has_add_permission(mock_request) is False

    def test_has_add_permission_no_perm(self, mapping_importer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        mock_request.user.has_perm.return_value = False
        assert mapping_importer_admin.has_add_permission(mock_request) is False

    def test_has_change_permission(self, mapping_importer_admin, mock_request):
        mapping_importer_admin.has_change_permission(mock_request)
        mock_request.user.has_perm.assert_called_with("country_workspace.change_mappingimporter")

    def test_has_delete_permission(self, mapping_importer_admin, mock_request):
        mapping_importer_admin.has_delete_permission(mock_request)
        mock_request.user.has_perm.assert_called_with("country_workspace.delete_mappingimporter")

    def test_has_view_permission(self, mapping_importer_admin, mock_request):
        mapping_importer_admin.has_view_permission(mock_request)
        mock_request.user.has_perm.assert_called_with("country_workspace.view_mappingimporter")

    @patch("country_workspace.workspaces.admin.mapping_importer.WorkspaceModelAdmin.save_model")
    def test_save_model_new(self, mock_super_save, mapping_importer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant
        obj = MagicMock(spec=CountryMappingImporter)
        form = MagicMock()
        with patch.object(mapping_importer_admin, "_invalidate_mapping_cache") as mock_invalidate:
            mapping_importer_admin.save_model(mock_request, obj, form, change=False)
            assert obj.office == mock_tenant
            assert obj.created_by == mock_request.user
            mock_super_save.assert_called_once_with(mock_request, obj, form, False)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.mapping_importer.WorkspaceModelAdmin.save_model")
    def test_save_model_existing(self, mock_super_save, mapping_importer_admin, mock_request):
        obj = MagicMock(spec=CountryMappingImporter)
        form = MagicMock()
        with patch.object(mapping_importer_admin, "_invalidate_mapping_cache") as mock_invalidate:
            mapping_importer_admin.save_model(mock_request, obj, form, change=True)
            mock_super_save.assert_called_once_with(mock_request, obj, form, True)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.mapping_importer.WorkspaceModelAdmin.delete_model")
    def test_delete_model(self, mock_super_delete, mapping_importer_admin, mock_request):
        obj = MagicMock(spec=CountryMappingImporter)
        with patch.object(mapping_importer_admin, "_invalidate_mapping_cache") as mock_invalidate:
            mapping_importer_admin.delete_model(mock_request, obj)
            mock_super_delete.assert_called_once_with(mock_request, obj)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.mapping_importer.WorkspaceModelAdmin.delete_queryset")
    def test_delete_queryset(self, mock_super_delete, mapping_importer_admin, mock_request):
        queryset = MagicMock()
        with patch.object(mapping_importer_admin, "_invalidate_mapping_cache") as mock_invalidate:
            mapping_importer_admin.delete_queryset(mock_request, queryset)
            mock_super_delete.assert_called_once_with(mock_request, queryset)
            mock_invalidate.assert_called_once()

    @patch("country_workspace.workspaces.admin.mapping_importer.cache")
    def test_invalidate_mapping_cache_with_tenant(self, mock_cache, mapping_importer_admin, mock_tenant):
        state.tenant = mock_tenant
        mapping_importer_admin._invalidate_mapping_cache()
        mock_cache.delete.assert_called_once_with(f"mapping_importer_list:{mock_tenant.pk}")

    @patch("country_workspace.workspaces.admin.mapping_importer.cache")
    def test_invalidate_mapping_cache_no_tenant(self, mock_cache, mapping_importer_admin):
        state.tenant = None
        mapping_importer_admin._invalidate_mapping_cache()
        mock_cache.delete.assert_not_called()

    @patch("country_workspace.workspaces.admin.mapping_importer.WorkspaceModelAdmin.get_form")
    def test_get_form(self, mock_super_get_form, mapping_importer_admin, mock_request, mock_tenant):
        state.tenant = mock_tenant

        mock_form = MagicMock()
        mock_data_checker_field = MagicMock()
        mock_form.base_fields = {"data_checker": mock_data_checker_field}
        mock_super_get_form.return_value = mock_form

        program1 = MagicMock(spec=CountryProgram, household_checker_id=101, individual_checker_id=102)
        program2 = MagicMock(spec=CountryProgram, household_checker_id=103, individual_checker_id=None)
        program3 = MagicMock(spec=CountryProgram, household_checker_id=None, individual_checker_id=104)

        with (
            patch("country_workspace.models.Program.objects.filter") as mock_program_filter,
            patch("hope_flex_fields.models.DataChecker.objects.filter") as mock_checker_filter,
        ):
            mock_program_filter.return_value = [program1, program2, program3]
            mock_checker_filter.return_value = "queryset"

            form = mapping_importer_admin.get_form(mock_request)

            mock_program_filter.assert_called_once_with(country_office=mock_tenant, enabled=True)
            expected_checker_ids = {101, 102, 103, 104}
            mock_checker_filter.assert_called_once_with(id__in=expected_checker_ids)
            assert form.base_fields["data_checker"].queryset == "queryset"
