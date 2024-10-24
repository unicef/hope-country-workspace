from django.contrib.admin import register
from django.http import HttpRequest

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

    def has_add_permission(self, request: "HttpRequest") -> bool:
        return False


# workspace.register(CountryJob, CountryJobAdmin)
