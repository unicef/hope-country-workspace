import factory
from testutils.factories import AutoRegisterModelFactory

from country_workspace.versioning.models import Version


class VersionFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"Version {n}")
    version = factory.Sequence(lambda n: "{n}")

    class Meta:
        model = Version
