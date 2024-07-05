import factory

from hope_country_workspace.security.models import CountryOffice, UserRole

from .base import AutoRegisterModelFactory
from .django_auth import GroupFactory
from .user import UserFactory


class CountryOfficeFactory(AutoRegisterModelFactory):
    class Meta:
        model = CountryOffice
        django_get_or_create = ("name",)


class UserRoleFactory(AutoRegisterModelFactory):
    class Meta:
        model = UserRole
        django_get_or_create = ("user", "group", "country_office")

    user = factory.SubFactory(UserFactory)
    group = factory.SubFactory(GroupFactory)
    country_office = factory.SubFactory(CountryOfficeFactory)
