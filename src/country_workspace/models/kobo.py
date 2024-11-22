from django.db import models


class KoboAsset(models.Model):
    uid = models.CharField(primary_key=True, max_length=32)


class KoboSubmission(models.Model):
    uuid = models.UUIDField(primary_key=True)
    asset = models.ForeignKey(KoboAsset, on_delete=models.CASCADE)
    data = models.JSONField()
