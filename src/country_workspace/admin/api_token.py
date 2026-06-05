from django.contrib.admin import ModelAdmin, display, register
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from country_workspace.models import APIToken


@register(APIToken)
class APITokenAdmin(ModelAdmin):
    list_display = (
        "masked_key",
        "user",
        "grant_type",
        "office_names",
        "valid_now",
        "valid_from",
        "valid_to",
        "created",
    )
    list_filter = ("grant_type", "offices", "valid_from", "valid_to")
    search_fields = ("key", "user__email", "offices__name")
    filter_horizontal = ("offices",)
    ordering = ("-created",)
    date_hierarchy = "created"
    autocomplete_fields = ("user",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[APIToken]:
        return super().get_queryset(request).select_related("user").prefetch_related("offices")

    def get_fields(self, request: HttpRequest, obj: APIToken | None = None) -> tuple[str, ...]:
        fields = ("user", "grant_type", "offices", "valid_from", "valid_to")
        return (*fields, "key", "valid_now", "created") if obj else fields

    def get_readonly_fields(self, request: HttpRequest, obj: APIToken | None = None) -> tuple[str, ...]:
        readonly = ("key", "valid_now", "created")
        return (*readonly, "user", "grant_type", "valid_from") if obj else readonly

    @display(description="Key", ordering="key")
    def masked_key(self, obj: APIToken) -> str:
        return f"{obj.key[:8]}…{obj.key[-4:]}"

    @display(description="Offices")
    def office_names(self, obj: APIToken) -> str:
        return ", ".join(map(str, obj.offices.all())) or "—"

    @display(boolean=True, description="Valid now")
    def valid_now(self, obj: APIToken) -> bool:
        return obj.is_valid_at(timezone.now())
