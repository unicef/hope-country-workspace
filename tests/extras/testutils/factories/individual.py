import factory

from country_workspace.models import Individual
from country_workspace.workspaces.models import CountryIndividual

from . import HouseholdFactory
from .base import AutoRegisterModelFactory
from .office import OfficeFactory
from .program import ProgramFactory


class IndividualFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    program = factory.SubFactory(ProgramFactory)
    household = factory.SubFactory(HouseholdFactory)
    full_name = factory.Sequence(lambda n: f"Individual {n}")

    class Meta:
        model = Individual
        django_get_or_create = ("full_name",)


class CountryIndividualFactory(IndividualFactory):

    class Meta:
        model = CountryIndividual
        django_get_or_create = ("full_name",)
