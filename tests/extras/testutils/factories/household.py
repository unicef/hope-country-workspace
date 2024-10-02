import factory

from hope_country_workspace.models import Household
from .office import CountryOfficeFactory

from .base import AutoRegisterModelFactory


class HouseholdFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(CountryOfficeFactory)
    name = factory.Sequence(lambda n: f"Household {n}")

    class Meta:
        model = Household
        django_get_or_create = ("name",)
