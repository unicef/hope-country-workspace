from django.contrib import admin
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.contrib.kobo.models.submission import KoboSubmission


@admin.register(KoboSubmission)
class KoboSubmissionAdmin(BaseModelAdmin):
    list_display = ("asset_uid", "last_submission_id")
    search_fields = ("asset_uid",)
    readonly_fields = ("asset_uid", "last_submission_id")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: KoboSubmission | None = None) -> bool:
        return False
