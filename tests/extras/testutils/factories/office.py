import factory

from country_workspace.models import CountryOffice

from .base import AutoRegisterModelFactory


class CountryOfficeFactory(AutoRegisterModelFactory):
    name = factory.Iterator(["Afghanistan", "Ukraine", "Niger", "South Sudan"])
    code = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))
    slug = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))

    class Meta:
        model = CountryOffice
        django_get_or_create = ("name",)
