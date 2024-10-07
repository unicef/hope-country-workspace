import factory

from country_workspace.models import CountryOffice

from .base import AutoRegisterModelFactory


class CountryOfficeFactory(AutoRegisterModelFactory):
    _COUNTRIES = [
        "Afghanistan",
        "Ukraine",
        "Niger",
        "South Sudan",
        "Somalia",
        "Belarus",
    ]
    name = factory.Iterator(_COUNTRIES)
    code = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))
    slug = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))

    class Meta:
        model = CountryOffice
        django_get_or_create = ("name",)
