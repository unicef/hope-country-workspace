from django.contrib import admin
from django.db import models
from django.http import HttpRequest

from ..models import MappingProfile, FieldMappingRule
from .base import BaseModelAdmin


@admin.register(MappingProfile)
class MappingProfileAdmin(BaseModelAdmin):
    list_display = ("name", "source_type", "import_schema", "is_active", "inheritance")
    list_filter = ("source_type", "import_schema", "program", "is_active")
    search_fields = ("name", "description")
    filter_horizontal = ("program",)
    fields = (
        "name",
        "description",
        "parent",
        "source_type",
        "import_schema",
        "program",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("created_by", "created_at", "updated_at")

    @admin.display(description="Inheritance Chain")
    def inheritance(self, obj: MappingProfile) -> str:
        return obj.get_inheritance_chain()

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[MappingProfile]:
        return super().get_queryset(request).select_related("parent", "created_by").prefetch_related("program")


@admin.register(FieldMappingRule)
class FieldMappingRuleAdmin(BaseModelAdmin):
    list_display = ("name", "profile", "order", "is_active")
    list_filter = ("profile", "is_active")
    search_fields = ("name", "description", "profile__name")
    ordering = ("profile", "order", "name")
    fields = (
        "name",
        "description",
        "profile",
        "expression",
        "order",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_by", "created_at", "updated_at")

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[FieldMappingRule]:
        return super().get_queryset(request).select_related("profile__parent", "created_by")
