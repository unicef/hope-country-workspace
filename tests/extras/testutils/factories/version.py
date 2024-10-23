import factory
from testutils.factories import AutoRegisterModelFactory

from country_workspace.versioning.models import Script


class ScriptFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"{n:>4}_script.py")
    version = factory.Sequence(lambda n: "{n}")

    class Meta:
        model = Script
