from django.db import models

from country_workspace.models import Program


class KoboAsset(models.Model):
    uid = models.CharField(primary_key=True, max_length=32, editable=False)
    name = models.CharField(max_length=128, null=True, editable=False)
    programs = models.ManyToManyField(Program)

    def __str__(self) -> str:
        return self.name or "No name"
