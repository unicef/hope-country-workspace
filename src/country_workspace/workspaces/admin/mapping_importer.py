from typing import Any

from django.contrib import admin
from django.core.cache import cache
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest

from country_workspace.state import state
from country_workspace.workspaces.models import CountryMappingImporter
from country_workspace.workspaces.options import WorkspaceModelAdmin
from country_workspace.workspaces.sites import workspace


@admin.register(CountryMappingImporter, site=workspace)
class CountryMappingImporterAdmin(WorkspaceModelAdmin):
    list_display = ("name", "data_checker", "description", "created_by", "created_at")
    list_filter = ("data_checker",)
    search_fields = ("name", "description")
    readonly_fields = ("office", "created_at", "last_modified", "created_by")
    fields = ("name", "description", "office", "data_checker", "rules", "created_by", "created_at", "last_modified")

    def get_queryset(self, request: HttpRequest) -> QuerySet[CountryMappingImporter]:
        """Filter mappings by current office/business area."""
        return CountryMappingImporter.objects.filter(office=state.tenant)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Check user permission and tenant selection."""
        return bool(state.tenant) and request.user.has_perm("country_workspace.add_mappingimporter")  # type: ignore[attr-defined]

    def has_change_permission(self, request: HttpRequest, obj: CountryMappingImporter | None = None) -> bool:
        """Check user permission to change mappings."""
        return request.user.has_perm("country_workspace.change_mappingimporter")  # type: ignore[attr-defined]

    def has_delete_permission(self, request: HttpRequest, obj: CountryMappingImporter | None = None) -> bool:
        """Check user permission to delete mappings."""
        return request.user.has_perm("country_workspace.delete_mappingimporter")  # type: ignore[attr-defined]

    def has_view_permission(self, request: HttpRequest, obj: CountryMappingImporter | None = None) -> bool:
        """Check user permission to view mappings."""
        return request.user.has_perm("country_workspace.view_mappingimporter")  # type: ignore[attr-defined]

    def save_model(self, request: HttpRequest, obj: CountryMappingImporter, form: ModelForm, change: bool) -> None:
        """Set office to current tenant and created_by on create, invalidate cache."""
        if not change:
            obj.office = state.tenant
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        self._invalidate_mapping_cache()

    def delete_model(self, request: HttpRequest, obj: CountryMappingImporter) -> None:
        """Delete mapping and invalidate cache."""
        super().delete_model(request, obj)
        self._invalidate_mapping_cache()

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[CountryMappingImporter]) -> None:
        """Delete multiple mappings and invalidate cache."""
        super().delete_queryset(request, queryset)
        self._invalidate_mapping_cache()

    def _invalidate_mapping_cache(self) -> None:
        """Invalidate cache keys related to mapping importers."""
        if state.tenant:
            cache_key = f"mapping_importer_list:{state.tenant.pk}"
            cache.delete(cache_key)

    def get_form(self, request: HttpRequest, obj: CountryMappingImporter | None = None, **kwargs: Any) -> ModelForm:
        """Customize form to filter data_checker by current office."""
        form = super().get_form(request, obj, **kwargs)
        if "data_checker" in form.base_fields:
            # Get the programs for current office to find their checkers
            from country_workspace.models import Program
            from hope_flex_fields.models import DataChecker

            programs = Program.objects.filter(country_office=state.tenant, enabled=True)
            checker_ids = set()
            for program in programs:
                if program.household_checker_id:  # type: ignore[attr-defined]
                    checker_ids.add(program.household_checker_id)  # type: ignore[attr-defined]
                if program.individual_checker_id:  # type: ignore[attr-defined]
                    checker_ids.add(program.individual_checker_id)  # type: ignore[attr-defined]

            form.base_fields["data_checker"].queryset = DataChecker.objects.filter(id__in=checker_ids)  # type: ignore[index]
        return form  # type: ignore[return-value]
