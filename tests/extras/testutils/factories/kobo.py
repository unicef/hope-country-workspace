from factory import fuzzy

from country_workspace.models import KoboAsset
from testutils.factories import AutoRegisterModelFactory


class KoboAssetFactory(AutoRegisterModelFactory):
    uid = fuzzy.FuzzyText()
    name = fuzzy.FuzzyText()

    class Meta:
        model = KoboAsset
