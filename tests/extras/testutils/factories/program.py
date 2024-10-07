import factory

from country_workspace.models import Program

from .base import AutoRegisterModelFactory
from .office import OfficeFactory


class ProgramFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    name = factory.Sequence(lambda n: f"Program {n}")

    class Meta:
        model = Program
        django_get_or_create = ("name",)
