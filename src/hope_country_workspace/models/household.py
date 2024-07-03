from django.db import models
from django.utils.translation import gettext as _

from hope_country_workspace.security.models import CountryOffice
from hope_country_workspace.tenant.db import TenantModel

BLANK = ""
IDP = "IDP"
REFUGEE = "REFUGEE"
OTHERS_OF_CONCERN = "OTHERS_OF_CONCERN"
HOST = "HOST"
NON_HOST = "NON_HOST"
RETURNEE = "RETURNEE"
RESIDENCE_STATUS_CHOICE = (
    (BLANK, _("None")),
    (IDP, _("Displaced  |  Internally Displaced People")),
    (REFUGEE, _("Displaced  |  Refugee / Asylum Seeker")),
    (OTHERS_OF_CONCERN, _("Displaced  |  Others of Concern")),
    (HOST, _("Non-displaced  |   Host")),
    (NON_HOST, _("Non-displaced  |   Non-host")),
    (RETURNEE, _("Displaced  |   Returnee")),
)


class Household(TenantModel):
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    flex_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Household"

    class Tenant:
        tenant_filter_field = "country_office"
