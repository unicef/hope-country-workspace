from django.contrib.postgres.fields import CICharField
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
    residence_status = models.CharField(max_length=254, choices=RESIDENCE_STATUS_CHOICE)
    country = models.CharField(max_length=12, blank=True, null=True)
    address = models.CharField(max_length=1024, blank=True)
    zip_code = models.CharField(max_length=12, blank=True, null=True)
    """location contains lowest administrative area info"""
    admin_area = models.CharField(max_length=12, blank=True, null=True)
    admin1 = models.CharField(max_length=12, blank=True, null=True)
    admin2 = models.CharField(max_length=12, blank=True, null=True)
    admin3 = models.CharField(max_length=12, blank=True, null=True)
    admin4 = models.CharField(max_length=12, blank=True, null=True)
    size = models.PositiveIntegerField(db_index=True, null=True, blank=True)
    representatives = models.ManyToManyField(
        to="Individual",
        through="IndividualRoleInHousehold",
        help_text="""This is only used to track collector (primary or secondary) of a household.
            They may still be a HOH of this household or any other household.
            Through model will contain the role (ROLE_CHOICE) they are connected with on.""",
        related_name="represented_households",
    )
    female_age_group_0_5_count = models.PositiveIntegerField(default=None, null=True)
    female_age_group_6_11_count = models.PositiveIntegerField(default=None, null=True)
    female_age_group_12_17_count = models.PositiveIntegerField(default=None, null=True)
    female_age_group_18_59_count = models.PositiveIntegerField(default=None, null=True)
    female_age_group_60_count = models.PositiveIntegerField(default=None, null=True)
    pregnant_count = models.PositiveIntegerField(default=None, null=True)
    male_age_group_0_5_count = models.PositiveIntegerField(default=None, null=True)
    male_age_group_6_11_count = models.PositiveIntegerField(default=None, null=True)
    male_age_group_12_17_count = models.PositiveIntegerField(default=None, null=True)
    male_age_group_18_59_count = models.PositiveIntegerField(default=None, null=True)
    male_age_group_60_count = models.PositiveIntegerField(default=None, null=True)
    female_age_group_0_5_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    female_age_group_6_11_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    female_age_group_12_17_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    female_age_group_18_59_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    female_age_group_60_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    male_age_group_0_5_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    male_age_group_6_11_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    male_age_group_12_17_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    male_age_group_18_59_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    male_age_group_60_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    children_count = models.PositiveIntegerField(default=None, null=True)
    male_children_count = models.PositiveIntegerField(default=None, null=True)
    female_children_count = models.PositiveIntegerField(default=None, null=True)
    children_disabled_count = models.PositiveIntegerField(default=None, null=True)
    male_children_disabled_count = models.PositiveIntegerField(default=None, null=True)
    female_children_disabled_count = models.PositiveIntegerField(
        default=None, null=True
    )
    flex_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Household"
        permissions = (("can_withdrawn", "Can withdrawn Household"),)

    class Tenant:
        tenant_filter_field = "country_office"
