from django.contrib import admin
from django import forms
from django.db import models
from django.http import HttpRequest

from country_workspace.mapping.models import FieldMappingRule
from country_workspace.admin.base import BaseModelAdmin


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

    def save_model(
        self, request: HttpRequest, obj: FieldMappingRule, form: forms.ModelForm | None = None, change: bool = False
    ) -> None:
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
