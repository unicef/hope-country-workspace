from django.db import models


class ImportConfig(models.Model):
    name = models.CharField(max_length=255)
