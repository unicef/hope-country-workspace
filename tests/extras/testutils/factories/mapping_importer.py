import factory
from .base import AutoRegisterModelFactory
from .smart_import import DataCheckerFactory

from country_workspace.models.mapping_importer import MappingImporter


class MappingImporterFactory(AutoRegisterModelFactory):
    data_checker = factory.SubFactory(DataCheckerFactory)
    name = factory.Sequence(lambda n: f"MappingImporter-{n}")
    description = factory.Faker("sentence")

    class Meta:
        model = MappingImporter
        django_get_or_create = ("data_checker",)
