import factory

from hope_country_workspace.security.models import UserRole

from .base import AutoRegisterModelFactory
from .django_auth import GroupFactory
from .office import CountryOfficeFactory
from .user import UserFactory


class UserRoleFactory(AutoRegisterModelFactory):
    class Meta:
        model = UserRole
        django_get_or_create = ("user", "group", "country_office")

    user = factory.SubFactory(UserFactory)
    group = factory.SubFactory(GroupFactory)
    country_office = factory.SubFactory(CountryOfficeFactory)
