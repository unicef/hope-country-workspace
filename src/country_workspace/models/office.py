from django.db import models


class OfficeManager(models.Manager):
    def sync(self):
        raise NotImplementedError("")


class Office(models.Model):
    HQ = "HQ"

    hope_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    code = models.CharField(max_length=100, blank=True, null=True, unique=True)
    name = models.CharField(max_length=100, blank=True, null=True, unique=True)
    slug = models.SlugField(max_length=100, blank=True, null=True, unique=True)
    objects = OfficeManager()

    def __str__(self):
        return str(self.name)
