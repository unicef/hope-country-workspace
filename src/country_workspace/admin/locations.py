from adminfilters.autocomplete import AutoCompleteFilter
from adminfilters.filters import NumberFilter
from admin_extra_buttons.api import button

from django.contrib import admin, messages
from django.db.models import Field
from django.http import HttpRequest

from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from ..models import AsyncJob, Area, AreaType, Country
from .base import BaseModelAdmin


@admin.register(Country)
class CountryAdmin(BaseModelAdmin):
    list_display = (
        "name",
        "iso_code2",
    )
    search_fields = (
        "name",
        "iso_code2",
    )
    readonly_fields = ("hope_id",)


@admin.register(AreaType)
class AreaTypeAdmin(BaseModelAdmin):
    list_display = ("name", "country", "area_level", "parent")
    list_filter = (("country", AutoCompleteFilter), ("area_level", NumberFilter))
    readonly_fields = ("hope_id",)

    search_fields = ("name",)
    autocomplete_fields = ("country",)
    raw_id_fields = ("country", "parent")


class AreaTypeFilter(admin.RelatedFieldListFilter):
    def field_choices(self, field: Field, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        if "area_type__country__exact" not in request.GET:
            return []
        return AreaType.objects.filter(country=request.GET["area_type__country__exact"]).values_list("id", "name")


@admin.register(Area)
class AreaAdmin(BaseModelAdmin):
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
    raw_id_fields = ("area_type", "parent")
    readonly_fields = ("hope_id",)

    @button()
    def sync(self, request: HttpRequest) -> None:
        job = AsyncJob.objects.create(
            description="Sync areas, areatypes, and countries from HOPE core",
            program=None,
            owner=request.user,
            type=AsyncJob.JobType.TASK,
            action=fqn("country_workspace.contrib.hope.sync.locations.sync_all"),
            batch=None,
            file=None,
            config={},
        )
        job.queue()
        self.message_user(request, _("Synchronization is scheduled."), messages.SUCCESS)
