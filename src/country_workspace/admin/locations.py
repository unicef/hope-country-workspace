import logging
from typing import TYPE_CHECKING

from adminfilters.autocomplete import AutoCompleteFilter
from adminfilters.filters import NumberFilter
from adminfilters.mixin import AdminFiltersMixin
from django.contrib import admin
from django.contrib.admin import ModelAdmin, RelatedFieldListFilter
from django.db.models import Field
from django.forms import FileField, FileInput, Form

from country_workspace.models.locations import Area, AreaType, Country, Currency
from country_workspace.admin.sync import SyncAdminMixin, SyncAdminConfig, TargetConfig, Target

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


class ImportCSVForm(Form):
    file = FileField(widget=FileInput(attrs={"accept": "text/csv"}))


@admin.register(Country)
class CountryAdmin(SyncAdminMixin, AdminFiltersMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "iso_code2",
        "iso_code3",
    )
    search_fields = (
        "name",
        "iso_code2",
        "iso_code3",
    )
    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.COUNTRIES),
            TargetConfig(target=Target.AREA_TYPES),
            TargetConfig(target=Target.AREAS),
        ],
    )


@admin.register(Currency)
class CurrencyAdmin(SyncAdminMixin, AdminFiltersMixin, admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.CURRENCIES),
        ],
    )


@admin.register(AreaType)
class AreaTypeAdmin(SyncAdminMixin, AdminFiltersMixin, admin.ModelAdmin):
    list_display = ("name", "country", "area_level", "parent")
    list_filter = (("country", AutoCompleteFilter), ("area_level", NumberFilter))
    search_fields = ("name",)
    autocomplete_fields = ("country",)
    raw_id_fields = ("country", "parent")
    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.AREA_TYPES),
            TargetConfig(target=Target.AREAS),
        ],
    )


class AreaTypeFilter(RelatedFieldListFilter):
    def field_choices(self, field: Field, request: "HttpRequest", model_admin: ModelAdmin) -> list[tuple[str, str]]:
        if "area_type__country__exact" not in request.GET:
            return []
        return AreaType.objects.filter(country=request.GET["area_type__country__exact"]).values_list("id", "name")


@admin.register(Area)
class AreaAdmin(SyncAdminMixin, AdminFiltersMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "area_type",
        "p_code",
    )
    list_filter = (
        ("area_type__country", AutoCompleteFilter),
        ("area_type", AreaTypeFilter),
    )
    search_fields = ("name", "p_code")
    autocomplete_fields = ("area_type", "parent")
    sync_config = SyncAdminConfig(
        targets=[
            TargetConfig(target=Target.AREAS),
        ],
    )
