import factory.fuzzy
from django.contrib.auth.models import Group

from country_workspace.models import User

from .base import AutoRegisterModelFactory


class UserFactory(AutoRegisterModelFactory):
    _password = "password"
    username = factory.LazyAttributeSequence(lambda i, n: "m%03d@example.com" % n)
    password = factory.django.Password(_password)
    email = factory.Sequence(lambda n: "m%03d@example.com" % n)

    class Meta:
        model = User
        django_get_or_create = ("username",)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        kwargs["email"] = kwargs["username"]
        ret = super()._create(model_class, *args, **kwargs)
        ret._password = cls._password
        return ret


class SuperUserFactory(UserFactory):
    username = factory.Sequence(lambda n: "superuser%03d@example.com" % n)
    email = factory.Sequence(lambda n: "superuser%03d@example.com" % n)
    is_superuser = True
    is_staff = True
    is_active = True


class GroupFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: "Group-%03d" % n)

    class Meta:
        model = Group
        django_get_or_create = ("name",)
