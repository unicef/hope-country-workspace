import factory
from factory import fuzzy
from faker import Faker

from country_workspace.models import Area, AreaType, Country, Currency
from testutils.factories import AutoRegisterModelFactory

faker = Faker()


class CountryFactory(AutoRegisterModelFactory):
    class Meta:
        model = Country
        django_get_or_create = ("name", "iso_code2")

    hope_id = factory.Sequence(lambda n: f"country-{n}")
    name = factory.LazyFunction(faker.unique.country)
    iso_code2 = factory.LazyFunction(lambda: faker.unique.country_code(representation="alpha-2"))
    iso_code3 = factory.LazyFunction(lambda: faker.unique.country_code(representation="alpha-3"))


class AreaTypeFactory(AutoRegisterModelFactory):
    class Meta:
        model = AreaType
        django_get_or_create = ("name", "country", "area_level")

    hope_id = factory.Sequence(lambda n: f"area-type-{n}")
    name = factory.LazyFunction(faker.domain_word)
    country = factory.SubFactory(CountryFactory)
    area_level = fuzzy.FuzzyChoice([1, 2, 3, 4])
    parent = None


class AreaFactory(AutoRegisterModelFactory):
    class Meta:
        model = Area
        django_get_or_create = ("p_code",)

    hope_id = factory.Sequence(lambda n: f"area-{n}")
    name = factory.LazyFunction(faker.city)
    parent = None
    p_code = factory.LazyFunction(lambda: faker.bothify(text="AF@@@@@@"))
    area_type = factory.SubFactory(AreaTypeFactory)


class CurrencyFactory(AutoRegisterModelFactory):
    class Meta:
        model = Currency
        django_get_or_create = ("code",)

    hope_id = factory.Sequence(lambda n: n + 1)
    code = factory.Sequence(lambda n: f"C{n:03d}")
    name = factory.Sequence(lambda n: f"Currency {n}")
