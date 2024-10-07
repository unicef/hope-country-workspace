import factory

from country_workspace.models import Household
from country_workspace.workspaces.models import CountryHousehold

from .base import AutoRegisterModelFactory
from .office import CountryOfficeFactory
from .program import ProgramFactory


class HouseholdFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(CountryOfficeFactory)
    program = factory.SubFactory(ProgramFactory)
    name = factory.Sequence(lambda n: f"Household {n}")

    class Meta:
        model = Household
        django_get_or_create = ("name",)


class CountryHouseholdFactory(HouseholdFactory):

    class Meta:
        model = CountryHousehold
        django_get_or_create = ("name",)
