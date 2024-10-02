import factory

from hope_country_workspace.security.models import CountryOffice

from .base import AutoRegisterModelFactory


class CountryOfficeFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: "Country #%s" % n)

    class Meta:
        model = CountryOffice
        django_get_or_create = ("name",)
