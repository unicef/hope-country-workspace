import factory

from country_workspace.models import Program
from country_workspace.workspaces.models import CountryProgram

from .base import AutoRegisterModelFactory
from .office import OfficeFactory


class ProgramFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    hope_id = factory.Sequence(lambda n: f"program-{n}")
    name = factory.Sequence(lambda n: f"Program {n}")

    class Meta:
        model = Program
        django_get_or_create = ("name",)


class CountryProgramFactory(ProgramFactory):
    class Meta:
        model = CountryProgram
        django_get_or_create = ("name",)
