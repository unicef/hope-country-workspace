from django.db import models
from django.utils.timezone import now


class Version(models.Model):
    name = models.CharField(max_length=255, unique=True)
    version = models.CharField(max_length=255)
    applied = models.DateTimeField(default=now)
