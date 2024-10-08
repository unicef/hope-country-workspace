from django.db import models
from django.utils.translation import gettext as _

from hope_flex_fields.models import DataChecker

from .base import BaseModel
from .office import Office


class Program(BaseModel):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    STATUS_CHOICE = (
        (ACTIVE, _("Active")),
        (DRAFT, _("Draft")),
        (FINISHED, _("Finished")),
    )
    CHILD_PROTECTION = "CHILD_PROTECTION"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    MULTI_PURPOSE = "MULTI_PURPOSE"
    NUTRITION = "NUTRITION"
    SOCIAL_POLICY = "SOCIAL_POLICY"
    WASH = "WASH"
    SECTOR_CHOICE = (
        (CHILD_PROTECTION, _("Child Protection")),
        (EDUCATION, _("Education")),
        (HEALTH, _("Health")),
        (MULTI_PURPOSE, _("Multi Purpose")),
        (NUTRITION, _("Nutrition")),
        (SOCIAL_POLICY, _("Social Policy")),
        (WASH, _("WASH")),
    )
    hope_id = models.CharField(max_length=200, unique=True, editable=False)
    country_office = models.ForeignKey(
        Office, on_delete=models.CASCADE, related_name="programs"
    )
    name = models.CharField(max_length=255)
    programme_code = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICE, db_index=True)
    sector = models.CharField(max_length=50, choices=SECTOR_CHOICE, db_index=True)
    active = models.BooleanField(default=False)

    household_checker = models.ForeignKey(
        DataChecker, blank=True, null=True, on_delete=models.CASCADE, related_name="+"
    )

    individual_checker = models.ForeignKey(
        DataChecker, blank=True, null=True, on_delete=models.CASCADE, related_name="+"
    )
    household_columns = models.TextField(
        default="__str__\nid", help_text="Columns to display ib the Admin table"
    )
    individual_columns = models.TextField(
        default="__str__\nid", help_text="Columns to display ib the Admin table"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Programme")
        verbose_name_plural = _("Programmes")
