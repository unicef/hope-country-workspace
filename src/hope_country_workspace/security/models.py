from django.contrib.auth.models import Group
from django.db import models

from unicef_security.models import AbstractUser, SecurityMixin


class CountryOffice(models.Model):
    HQ = "HQ"
    name = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        app_label = "security"


class User(SecurityMixin, AbstractUser):

    class Meta:
        app_label = "security"
        abstract = False


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    class Meta:
        app_label = "security"
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_unique_role",
                fields=["user", "country_office", "group"],
            ),
        )
