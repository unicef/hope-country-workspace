from django.db import models
from django.utils.translation import gettext as _

from hope_country_workspace.tenant.db import TenantModel


class Document(TenantModel):
    STATUS_PENDING = "PENDING"
    STATUS_VALID = "VALID"
    STATUS_NEED_INVESTIGATION = "NEED_INVESTIGATION"
    STATUS_INVALID = "INVALID"
    STATUS_CHOICES = (
        (STATUS_PENDING, _("Pending")),
        (STATUS_VALID, _("Valid")),
        (STATUS_NEED_INVESTIGATION, _("Need Investigation")),
        (STATUS_INVALID, _("Invalid")),
    )

    document_number = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(blank=True)
    individual = models.ForeignKey(
        "Individual", related_name="documents", on_delete=models.CASCADE
    )
    type = models.ForeignKey(
        "DocumentType", related_name="documents", on_delete=models.CASCADE
    )
    country = models.ForeignKey(
        "geo.Country", blank=True, null=True, on_delete=models.PROTECT
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    cleared = models.BooleanField(default=False)
    cleared_by = models.ForeignKey("account.User", null=True, on_delete=models.SET_NULL)
    issuance_date = models.DateTimeField(null=True, blank=True)
    expiry_date = models.DateTimeField(null=True, blank=True, db_index=True)
    is_migration_handled = models.BooleanField(default=False)
