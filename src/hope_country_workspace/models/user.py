from typing import Any, TYPE_CHECKING
from django.db import models

from hope_country_workspace.tenant.db import TenantModel

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

if TYPE_CHECKING:
    from hope_country_report.types.hope import TBusinessArea


DATE_FORMATS: list[tuple[str, str]]
TIME_FORMATS: list[tuple[str, str]]
sample = datetime.datetime(2000, 12, 31, 23, 59)

DATE_FORMATS = [(fmt, dateformat.format(sample, fmt)) for fmt in ["Y M d", "j M Y", "Y-m-d", "Y M d, l", "D, j M Y"]]
TIME_FORMATS = [(fmt, dateformat.format(sample, fmt)) for fmt in ["h:i a", "H:i"]]



class User(TimeStampedModel, SecurityMixin, AbstractUser):  # type: ignore
    timezone: ZoneInfo
    timezone = TimeZoneField(verbose_name=_("Timezone"), default="UTC")
    language = models.CharField(verbose_name=_("Language"), max_length=10, choices=settings.LANGUAGES, default="en")
    date_format = models.CharField(
        verbose_name=_("Date Format"),
        max_length=20,
        choices=DATE_FORMATS,
        default=DATE_FORMATS[0][0],
        help_text=_("Only applied to user interface. It will not be applied to the reports"),
    )
    time_format = models.CharField(
        verbose_name=_("Time Format"),
        max_length=20,
        choices=TIME_FORMATS,
        default=TIME_FORMATS[0][0],
        help_text=_("Only applied to user interface. It will not be applied to the reports"),
    )

    class Meta:
        permissions = (("access_api", "Can access API"),)
        app_label = "core"
        swappable = "AUTH_USER_MODEL"

    @cached_property
    def datetime_format(self) -> str:
        return f"{self.date_format} {self.time_format}"

    @cached_property
    def friendly_name(self) -> str:
        return self.first_name or self.username

    @cached_property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}" or self.username


class UserRole(TimeStampedModel, models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles")
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    expires = models.DateField(blank=True, null=True)

    class Meta:
        app_label = "core"
        unique_together = ("user", "group", "country_office")

    def __str__(self) -> str:
        return f"{self.user.username} {self.group.name}"
