from ...state import state
from ..options import WorkspaceModelAdmin


class CountryCheckerAdmin(WorkspaceModelAdmin):
    exclude = ("country_office",)

    def save_model(self, request, obj, form, change):
        obj.country_office = state.tenant
        super().save_model(request, obj, form, change)
