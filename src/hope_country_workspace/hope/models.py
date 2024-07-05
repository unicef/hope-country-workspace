from django.db import models
from hope_country_workspace.security.models import CountryOffice as CountryOffice_


class CountryOffice(CountryOffice_):
    class Meta:
        proxy = True


class Program(models.Model):
    name = models.CharField(max_length=255)
