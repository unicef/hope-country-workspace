import factory
from .base import AutoRegisterModelFactory
from .office import OfficeFactory

from country_workspace.models.transformer import Transformer


class TransformerFactory(AutoRegisterModelFactory):
    office = factory.SubFactory(OfficeFactory)
    name = factory.Sequence(lambda n: f"Transformer-{n}")
    description = factory.Faker("sentence")
    value_transformations = ""

    class Meta:
        model = Transformer
        django_get_or_create = ("office", "name")
