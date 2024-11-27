from django.db import models

from country_workspace.models import Program


class KoboAsset(models.Model):
    uid = models.CharField(primary_key=True, max_length=32, editable=False)
    name = models.CharField(max_length=128, null=True, editable=False)
    programs = models.ManyToManyField(Program)

    def __str__(self) -> str:
        return self.name or "No name"



class KoboQuestion(models.Model):
    asset = models.ForeignKey(KoboAsset, on_delete=models.CASCADE)
    key = models.CharField(max_length=128, null=True, editable=False)
    labels = models.JSONField(default=list)

    class Meta:
        unique_together = ("asset", "key")


class KoboSubmission(models.Model):
    uuid = models.UUIDField(primary_key=True)
    asset = models.ForeignKey(KoboAsset, on_delete=models.CASCADE)
    data = models.JSONField(default=dict)
