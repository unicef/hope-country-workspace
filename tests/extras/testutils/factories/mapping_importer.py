import factory
from .base import AutoRegisterModelFactory
from .office import OfficeFactory
from .smart_import import DataCheckerFactory

from country_workspace.models.mapping_importer import MappingImporter


class MappingImporterFactory(AutoRegisterModelFactory):
    office = factory.SubFactory(OfficeFactory)
    data_checker = factory.SubFactory(DataCheckerFactory)
    name = factory.Sequence(lambda n: f"MappingImporter-{n}")
    description = factory.Faker("sentence")
    rules = ""

    class Meta:
        model = MappingImporter
        django_get_or_create = ("office", "name")
