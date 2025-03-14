import factory

from testutils.factories import AutoRegisterModelFactory, OfficeFactory

from country_workspace.workspaces.models import CountryChecker


class CountryCheckerFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda d: "DataChecker-%s" % d)

    country_office = factory.SubFactory(OfficeFactory)

    class Meta:
        model = CountryChecker
