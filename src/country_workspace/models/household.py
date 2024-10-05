from django.db import models
from django.utils.translation import gettext as _

from .office import CountryOffice
from .program import Program


class Household(models.Model):
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    name = models.CharField(_("Name"), max_length=255)
    flex_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Household"

    class Tenant:
        tenant_filter_field = "country_office"
