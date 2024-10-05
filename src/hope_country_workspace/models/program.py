from django.db import models

from ..security.models import CountryOffice


class Program(models.Model):
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
