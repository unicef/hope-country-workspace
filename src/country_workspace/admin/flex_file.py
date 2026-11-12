from io import BytesIO
from uuid import UUID

from adminfilters.autocomplete import AutoCompleteFilter
from adminfilters.filters import ValueFilter
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from hope_flex_fields.references import DEFAULT_MIMETYPE

from ..models import FlexFieldFile
from .base import BaseModelAdmin


@admin.register(FlexFieldFile)
class FlexFieldFileAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "field_name",
        "original_filename",
        "mimetype",
        "size",
        "content_type",
        "object_id",
        "created_at",
    )
    list_select_related = ("content_type",)
    search_fields = ("id", "field_name", "original_filename", "checksum", "object_id")
    list_filter = (
        ("content_type", AutoCompleteFilter),
        ("field_name", ValueFilter),
        ("mimetype", ValueFilter),
        "created_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    exclude = ("content",)
    readonly_fields = (
        "preview",
        "id",
        "content_type",
        "object_id",
        "field_name",
        "mimetype",
        "size",
        "original_filename",
        "checksum",
        "created_at",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[FlexFieldFile]:
        return super().get_queryset(request).defer("content")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: FlexFieldFile | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: FlexFieldFile | None = None) -> bool:
        return False

    def get_urls(self) -> list:
        info = self.opts.app_label, self.opts.model_name
        return [
            path(
                "<uuid:object_id>/content/",
                self.admin_site.admin_view(self.content_view),
                name="%s_%s_content" % info,
            ),
            *super().get_urls(),
        ]

    def content_view(self, request: HttpRequest, object_id: UUID) -> HttpResponse:
        if not self.has_view_permission(request):
            raise PermissionDenied
        flex_file = FlexFieldFile.objects.with_content().filter(pk=object_id).first()
        if flex_file is None:
            raise Http404
        response = FileResponse(
            BytesIO(flex_file.content_bytes),
            content_type=flex_file.mimetype or DEFAULT_MIMETYPE,
            filename=flex_file.original_filename or str(flex_file.pk),
        )
        response["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @admin.display(description=_("Preview"))
    def preview(self, obj: FlexFieldFile) -> str:
        url = reverse("admin:%s_%s_content" % (self.opts.app_label, self.opts.model_name), args=[obj.pk])
        if (obj.mimetype or "").startswith("image/"):
            return format_html(
                '<a href="{0}" target="_blank">'
                '<img src="{0}" alt="{1}" style="max-width: 600px; max-height: 600px;">'
                "</a>",
                url,
                obj.original_filename or obj.field_name,
            )
        return format_html('<a href="{}" target="_blank">{}</a>', url, _("Open file"))
