from django.db import models
from django.utils.timezone import now


class Script(models.Model):
    name = models.CharField(max_length=255, unique=True)
    version = models.CharField(max_length=255)
    applied = models.DateTimeField(default=now)

    def num(self) -> str:
        return self.name.split("_", 1)[0]

    num.ordering = ("name",)

    def label(self) -> str:
        return self.name.split("_", 1)[1]
