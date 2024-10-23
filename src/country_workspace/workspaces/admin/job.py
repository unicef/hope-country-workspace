from django.contrib.admin import register

from ..models import CountryJob
from ..options import WorkspaceModelAdmin
from ..sites import workspace


@register(CountryJob, site=workspace)
class CountryJobAdmin(WorkspaceModelAdmin):
    list_display = (
        "name",
        "sector",
        "status",
        "active",
    )

    def has_add_permission(self, request):
        return False


# workspace.register(CountryJob, CountryJobAdmin)
