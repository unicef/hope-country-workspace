from factory import fuzzy
from factory.declarations import SubFactory

from testutils.factories import AutoRegisterModelFactory, ProgramFactory


class KoboAssetFactory(AutoRegisterModelFactory):
    uid = fuzzy.FuzzyText()
    name = fuzzy.FuzzyText()
    program = SubFactory(ProgramFactory)
