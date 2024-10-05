import factory
from hope_smart_import.models import Configuration

from .base import AutoRegisterModelFactory
from .smart_fields import DataCheckerFactory


class ConfigurationFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"Configuration {n}")
    checker = factory.SubFactory(DataCheckerFactory)

    class Meta:
        model = Configuration
