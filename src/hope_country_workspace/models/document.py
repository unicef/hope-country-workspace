from django.db import models

from hope_country_workspace.tenant.db import TenantModel


class Document(TenantModel):
    document_number = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(blank=True)
    individual = models.ForeignKey(
        "Individual", related_name="documents", on_delete=models.CASCADE
    )

    class Tenant:
        tenant_filter_field = "individual__household__country_office"
