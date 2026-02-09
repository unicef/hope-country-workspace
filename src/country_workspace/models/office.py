from django.db import models

from .base import BaseModel
from .locations import Country


class Office(BaseModel):
    HQ = "HQ"

    hope_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    name = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    long_name = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    code = models.CharField(max_length=100, blank=True, null=True, db_index=True, unique=True)
    slug = models.SlugField(max_length=100, blank=True, null=True, db_index=True, unique=True)
    active = models.BooleanField(default=False, db_index=True, help_text="Is this office active in the HOPE core?")
    kobo_country_code = models.CharField(max_length=3, blank=True, null=True)
    extra_fields = models.JSONField(default=dict, blank=True, null=False)
    enabled = models.BooleanField(default=True, db_index=True, help_text="Is this office enabled in the workspace?")
    countries = models.ManyToManyField(Country, blank=True, related_name="%(class)ss")

    def __str__(self) -> str:
        return str(self.name)

    class Meta:
        ordering = ["name"]
        permissions = (("sync_office", "Can sync office"),)
