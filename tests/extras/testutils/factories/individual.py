import factory

from country_workspace.models import Individual

from . import HouseholdFactory
from .base import AutoRegisterModelFactory
from .office import CountryOfficeFactory
from .program import ProgramFactory


class IndividualFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(CountryOfficeFactory)
    program = factory.SubFactory(ProgramFactory)
    household = factory.SubFactory(HouseholdFactory)
    full_name = factory.Sequence(lambda n: f"Individual {n}")

    class Meta:
        model = Individual
        django_get_or_create = ("full_name",)
