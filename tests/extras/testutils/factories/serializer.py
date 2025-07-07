import factory
from country_workspace.models.serializer import DataSerializer
from .base import AutoRegisterModelFactory


class DataSerializerFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"serializer-{n}")
    code = "function test(data) { return data; }"

    class Meta:
        model = DataSerializer
        django_get_or_create = ("name",)
