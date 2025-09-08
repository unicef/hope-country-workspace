from django.db import models


class BeneficiaryGroup(models.Model):
    hope_id = models.CharField(max_length=100, blank=True, null=True, unique=True, help_text="Unique ID from HOPE")
    name = models.CharField(max_length=255, unique=True, help_text="Name of the beneficiary group")
    group_label = models.CharField(max_length=255, help_text="Label for the group")
    group_label_plural = models.CharField(max_length=255, help_text="Plural label for the group")
    member_label = models.CharField(max_length=255, help_text="Label for the member")
    member_label_plural = models.CharField(max_length=255, help_text="Plural label for the member")
    master_detail = models.BooleanField(default=True, help_text="Indicates if this is a master-detail group")

    class Meta:
        verbose_name = "Beneficiary Group"
        verbose_name_plural = "Beneficiary Groups"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name
