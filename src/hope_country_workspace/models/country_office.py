from typing import Any, TYPE_CHECKING

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.gis.db.models import MultiPolygonField
from django.db import models
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import dateformat
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from timezone_field import TimeZoneField
from unicef_security.models import AbstractUser, SecurityMixin, TimeStampedModel

from hope_country_report.apps.hope.models import Country
from hope_country_report.state import state
from django.db import models

from hope_country_workspace.tenant.db import TenantModel

if TYPE_CHECKING:
    from hope_country_report.types.hope import TBusinessArea


class CountryOfficeManager(models.Manager["CountryOffice"]):
    def get_queryset(self) -> QuerySet["CountryOffice"]:
        if state.tenant:
            return super().get_queryset().filter(id=state.tenant.pk)
        return super().get_queryset()

    def sync(self) -> None:
        from hope_country_report.apps.hope.models import BusinessArea

        CountryOffice.objects.update_or_create(
            hope_id=CountryOffice.HQ,
            defaults={
                "name": "Headquarter",
                "slug": "-",
                "long_name": "Headquarter",
                "active": True,
                "code": CountryOffice.HQ,
            },
        )
        ba: TBusinessArea
        for ba in BusinessArea.objects.all():
            values = {
                "hope_id": str(ba.id),
                "name": ba.name,
                "active": ba.active,
                "code": ba.code,
                "long_name": ba.long_name,
                "region_code": ba.region_code,
                "slug": slugify(ba.name),
            }
            # country: Country = ba.countries.first()
            # shape: CountryShape = CountryShape.objects.filter()
            CountryOffice.objects.update_or_create(hope_id=ba.id, defaults=values)
        self.link_shapes()

    def link_shapes(self) -> QuerySet["CountryOffice"]:
        c: CountryOffice
        for c in CountryOffice.objects.filter(shape__isnull=True):
            if c.business_area:
                country: Country = c.business_area.countries.first()
                if country:
                    c.shape = CountryShape.objects.filter(iso2=country.iso_code2).first()
                else:
                    c.shape = CountryShape.objects.filter(name__iexact=c.slug).first()

                if c.shape:
                    c.save(update_fields=["shape"])


class CountryOffice(TimeStampedModel, models.Model):
    HQ = "HQ"
    name = models.CharField(max_length=100, blank=True, null=True)
    active = models.BooleanField(default=False, blank=True, null=True)
    code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    long_name = models.CharField(max_length=255, blank=True, null=True)
    region_code = models.CharField(max_length=8, blank=True, null=True)
    region_name = models.CharField(max_length=8, blank=True, null=True)
    hope_id = models.CharField(unique=True, max_length=100, blank=True, null=True)
    slug = models.SlugField(unique=True, null=True)

    timezone = TimeZoneField(verbose_name=_("Timezone"), default="UTC", help_text=_("Country default timezone."))
    locale = models.CharField(
        verbose_name=_("Locale"),
        max_length=10,
        choices=settings.LANGUAGES,
        default="en",
        help_text=_("Country default locale. It affects dates and number formats"),
    )
    settings = models.JSONField(default=dict, blank=True)
    shape = models.ForeignKey(CountryShape, blank=True, null=True, on_delete=models.SET_NULL)
    objects = CountryOfficeManager()

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    @cached_property
    def geom(self) -> "MultiPolygonField[Any, Any]|None":
        return self.shape.mpoly

    def get_map_settings(self) -> dict[str, int | float]:
        lat = self.settings.get("map", {}).get("center", {}).get("lat", 0)
        lng = self.settings.get("map", {}).get("center", {}).get("lng", 0)
        zoom = self.settings.get("map", {}).get("zoom", 8)
        return {
            "lat": lat,
            "lng": lng,
            "zoom": zoom,
        }

    def get_absolute_url(self) -> str:
        return reverse("office-index", args=[self.slug])
