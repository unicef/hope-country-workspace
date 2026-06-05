from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http.response import HttpResponse

from country_workspace.state import state
from country_workspace.workspaces.admin.transformer import CountryTransformerAdmin, RunTransformerForm
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


class TestRunTransformerForm:
    def _build_mock_queryset(self) -> MagicMock:
        qs = MagicMock()
        qs.filter.return_value = qs
        qs.select_related.return_value = qs
        qs.all.return_value = qs
        return qs

    @patch("country_workspace.workspaces.admin.transformer.Batch.objects")
    def test_choices_without_program(self, mock_batch_objects):
        qs = self._build_mock_queryset()
        mock_batch_objects.order_by.return_value = qs

        form = RunTransformerForm()

        choices = [choice[0] for choice in form.fields["apply_to"].choices]
        assert choices == [
            RunTransformerForm.ApplyToOptions.INDIVIDUALS,
            RunTransformerForm.ApplyToOptions.BOTH,
        ]

    @patch("country_workspace.workspaces.admin.transformer.Batch.objects")
    def test_choices_master_detail_program(self, mock_batch_objects):
        qs = self._build_mock_queryset()
        mock_batch_objects.order_by.return_value = qs
        program = MagicMock(is_master_detail=True)

        form = RunTransformerForm(program=program)

        choices = [choice[0] for choice in form.fields["apply_to"].choices]
        assert choices == [
            RunTransformerForm.ApplyToOptions.HOUSEHOLDS,
            RunTransformerForm.ApplyToOptions.INDIVIDUALS,
            RunTransformerForm.ApplyToOptions.BOTH,
        ]

    @patch("country_workspace.workspaces.admin.transformer.Batch.objects")
    def test_choices_non_master_detail_program(self, mock_batch_objects):
        qs = self._build_mock_queryset()
        mock_batch_objects.order_by.return_value = qs
        program = MagicMock(is_master_detail=False)

        form = RunTransformerForm(program=program)

        choices = [choice[0] for choice in form.fields["apply_to"].choices]
        assert choices == [RunTransformerForm.ApplyToOptions.INDIVIDUALS]


class TestRunOnExistingRecords:
    def _build_request(self, method: str = "GET", post_data: dict | None = None, has_perm: bool = True) -> MagicMock:
        request = MagicMock(spec=HttpRequest)
        request.method = method
        request.POST = post_data or {}
        request.user = MagicMock(spec=User)
        request.user.has_perm.return_value = has_perm
        return request

    def test_returns_404_when_transformer_not_found(self, transformer_admin):
        request = self._build_request()
        with patch(
            "country_workspace.workspaces.admin.transformer.CountryTransformerAdmin.get_object",
            return_value=None,
        ):
            response = transformer_admin.run_on_existing_records(transformer_admin, request, "123")
        assert response.status_code == 404

    def test_get_renders_form(self, transformer_admin):
        request = self._build_request("GET")
        transformer = MagicMock(pk=1, name="T1")
        state.tenant = MagicMock()
        state.program = MagicMock()

        with (
            patch(
                "country_workspace.workspaces.admin.transformer.CountryTransformerAdmin.get_object",
                return_value=transformer,
            ),
            patch(
                "country_workspace.workspaces.admin.transformer.render", return_value=HttpResponse("ok")
            ) as mock_render,
        ):
            response = transformer_admin.run_on_existing_records(transformer_admin, request, "1")

        assert response.status_code == 200
        mock_render.assert_called_once()

    def test_post_invalid_form_shows_error(self, transformer_admin):
        request = self._build_request("POST", {"apply": "yes"})
        transformer = MagicMock(pk=1, name="T1")
        state.tenant = MagicMock()
        state.program = MagicMock()

        mock_form = MagicMock()
        mock_form.is_valid.return_value = False

        with (
            patch(
                "country_workspace.workspaces.admin.transformer.CountryTransformerAdmin.get_object",
                return_value=transformer,
            ),
            patch("country_workspace.workspaces.admin.transformer.RunTransformerForm", return_value=mock_form),
            patch.object(transformer_admin, "message_user") as mock_message_user,
            patch("country_workspace.workspaces.admin.transformer.render", return_value=HttpResponse("ok")),
        ):
            transformer_admin.run_on_existing_records(transformer_admin, request, "1")

        mock_message_user.assert_called()
        assert "Please correct the errors below." in mock_message_user.call_args.args[1]

    def test_post_valid_without_permission_redirects_to_change(self, transformer_admin):
        request = self._build_request("POST", {"apply": "yes"}, has_perm=False)
        transformer = MagicMock(pk=1, name="T1")
        program = MagicMock(is_master_detail=True)
        batch = MagicMock(pk=10, name="Batch 1", program=program)
        state.tenant = MagicMock()
        state.program = MagicMock()

        mock_form = MagicMock()
        mock_form.is_valid.return_value = True
        mock_form.cleaned_data = {
            "batch": batch,
            "apply_to": RunTransformerForm.ApplyToOptions.BOTH,
        }

        with (
            patch(
                "country_workspace.workspaces.admin.transformer.CountryTransformerAdmin.get_object",
                return_value=transformer,
            ),
            patch("country_workspace.workspaces.admin.transformer.RunTransformerForm", return_value=mock_form),
            patch(
                "country_workspace.workspaces.admin.transformer.CountryTransformerAdmin.get_change_url",
                return_value="/change/",
            ) as mock_get_change_url,
            patch.object(transformer_admin, "message_user") as mock_message_user,
        ):
            response = transformer_admin.run_on_existing_records(transformer_admin, request, "1")

        assert response.status_code == 302
        assert response.url == "/change/"
        mock_get_change_url.assert_called_once_with(request, transformer)
        assert "do not have permission" in mock_message_user.call_args.args[1]

    def test_post_valid_schedules_job_for_both_in_master_detail(self, transformer_admin):
        request = self._build_request("POST", {"apply": "yes"}, has_perm=True)
        transformer = MagicMock(pk=99, name="Eligibility Rule")
        program = MagicMock(is_master_detail=True)
        batch = MagicMock(pk=10, name="Batch 1", program=program)
        state.tenant = MagicMock()
        state.program = MagicMock()

        mock_form = MagicMock()
        mock_form.is_valid.return_value = True
        mock_form.cleaned_data = {
            "batch": batch,
            "apply_to": RunTransformerForm.ApplyToOptions.BOTH,
        }
        job = MagicMock()

        with (
            patch(
                "country_workspace.workspaces.admin.transformer.CountryTransformerAdmin.get_object",
                return_value=transformer,
            ),
            patch("country_workspace.workspaces.admin.transformer.RunTransformerForm", return_value=mock_form),
            patch(
                "country_workspace.workspaces.admin.transformer.AsyncJob.objects.create", return_value=job
            ) as mock_create,
            patch("country_workspace.workspaces.admin.transformer.reverse", return_value="/batch/"),
            patch.object(transformer_admin, "message_user") as mock_message_user,
        ):
            response = transformer_admin.run_on_existing_records(transformer_admin, request, "99")

        assert response.status_code == 302
        assert response.url == "/batch/"
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["config"] == {
            "batch_id": 10,
            "household_transformer_id": 99,
            "individual_transformer_id": 99,
        }
        job.queue.assert_called_once()
        assert "scheduled" in mock_message_user.call_args.args[1].lower()
