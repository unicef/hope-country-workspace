import factory
from factory import fuzzy
from faker import Faker

from country_workspace.models import Area, AreaType, Country
from testutils.factories import AutoRegisterModelFactory

faker = Faker()


class CountryFactory(AutoRegisterModelFactory):
    class Meta:
        model = Country
        django_get_or_create = (
            "name",
            "iso_code2",
        )

    name = "Afghanistan"
    iso_code2 = "AF"


class AreaTypeFactory(AutoRegisterModelFactory):
    class Meta:
        model = AreaType
        django_get_or_create = ("name", "country", "area_level")

    name = factory.LazyFunction(faker.domain_word)
    country = factory.SubFactory(CountryFactory)
    area_level = fuzzy.FuzzyChoice([1, 2, 3, 4])
    parent = None


class AreaFactory(AutoRegisterModelFactory):
    class Meta:
        model = Area
        django_get_or_create = ("p_code",)

    name = factory.LazyFunction(faker.city)
    parent = None
    p_code = factory.LazyFunction(lambda: faker.bothify(text="AF@@@@@@"))
    area_type = factory.SubFactory(AreaTypeFactory)
