from contextlib import ContextDecorator
from random import choice
from unittest.mock import Mock

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from faker import Faker

from country_workspace.models import Office, Program, UserRole
from country_workspace.state import state
from country_workspace.workspaces.models import CountryProgram

from .factories import GroupFactory

whitespace = " \t\n\r\v\f"
lowercase = "abcdefghijklmnopqrstuvwxyz"
uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
letters = lowercase + uppercase
ascii_lowercase = lowercase
ascii_uppercase = uppercase
ascii_letters = ascii_lowercase + ascii_uppercase

faker = Faker()


def text(length, choices=ascii_letters):
    """returns a random (fixed length) string

    :param length: string length
    :param choices: string containing all the chars can be used to build the string

    .. seealso::
       :py:func:`rtext`
    """
    return "".join(choice(choices) for x in range(length))


def get_group(name=None, permissions=None):
    group = GroupFactory(name=(name or text(5)))
    permission_names = permissions or []
    for permission_name in permission_names:
        try:
            app_label, codename = permission_name.split(".")
        except ValueError:
            raise ValueError(f"Invalid permission name `{permission_name}`")
        try:
            permission = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        except Permission.DoesNotExist:
            raise Permission.DoesNotExist("Permission `{0}` does not exists", permission_name)

        group.permissions.add(permission)
    return group


class set_current_user(ContextDecorator):  # noqa
    def __init__(self, user):
        self.user = user

    def __enter__(self):
        r = Mock()
        r.user = self.user
        self.state = state.set(request=r)
        self.state.__enter__()

    def __exit__(self, e_typ, e_val, trcbak):
        self.state.__exit__(e_typ, e_val, trcbak)
        if e_typ:
            raise e_typ(e_val).with_traceback(trcbak)


class user_grant_role(ContextDecorator):  # noqa
    caches = [
        "_group_perm_cache",
        "_user_perm_cache",
        "_dsspermissionchecker",
        "_officepermissionchecker",
        "_perm_cache",
        "_dss_acl_cache",
    ]

    def __init__(self, user, country_office_or_program, group=settings.ANALYST_GROUP_NAME):
        self.user = user
        if isinstance(group, str):
            self.group, __ = Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
        else:
            self.group = group
        if isinstance(country_office_or_program, Office):
            self.country_office = country_office_or_program
            self.program = None
        else:
            self.country_office = country_office_or_program.country_office
            self.program = country_office_or_program

    def __enter__(self):
        for cache in self.caches:
            if hasattr(self.user, cache):
                delattr(self.user, cache)
        if self.country_office:
            cache_name = "_power_query_%s_perm_cache" % self.country_office.pk
            if hasattr(self.user, cache_name):
                delattr(self.user, cache_name)
        __, self.is_added = UserRole.objects.get_or_create(
            country_office=self.country_office,
            program=self.program,
            user=self.user,
            group=self.group,
        )
        return self

    def __exit__(self, e_typ, e_val, trcbak):
        if self.is_added:
            self.user.groups.remove(self.group)

        if e_typ:
            raise e_val.with_traceback(trcbak)

    def start(self):
        """Activate a patch, returning any created mock."""
        return self.__enter__()

    def stop(self):
        """Stop an active patch."""
        return self.__exit__(None, None, None)


class user_grant_permissions(ContextDecorator):  # noqa
    caches = [
        "_group_perm_cache",
        "_user_perm_cache",
        "_dsspermissionchecker",
        "_officepermissionchecker",
        "_perm_cache",
        "_dss_acl_cache",
        "_tenant_cache",
    ]

    def __init__(
        self,
        user,
        permissions=None,
        country_office_or_program=None,
        group_name=None,
        set_superuser=None,
        set_staff=None,
    ):
        self.user = user
        if not isinstance(permissions, (list, tuple)):
            permissions = [permissions]
        self.permissions = permissions
        self.group_name = group_name
        self.group = None
        self.superuser = set_superuser
        self.staff = set_staff
        self.pre = {}

        if isinstance(country_office_or_program, Office):
            self.country_office = country_office_or_program
            self.program = None
        elif isinstance(country_office_or_program, (Program, CountryProgram)):
            self.country_office = country_office_or_program.country_office
            self.program = country_office_or_program
        else:
            raise ValueError(country_office_or_program)

    def __enter__(self):
        for cache in self.caches:
            if hasattr(self.user, cache):
                delattr(self.user, cache)
        match self.staff:
            case None:
                pass
            case True:
                self.pre["is_staff"] = self.user.is_staff
                self.user.is_staff = self.staff
            case False:
                self.pre["is_staff"] = self.user.is_staff
                self.user.is_staff = self.staff
        match self.superuser:
            case None:
                pass
            case True:
                self.pre["is_superuser"] = self.user.is_superuser
                self.user.is_superuser = self.superuser
            case False:
                self.pre["is_superuser"] = self.user.is_superuser
                self.user.is_superuser = self.superuser
        self.user.save()
        self.user._password = "password"
        self.group = get_group(name=self.group_name, permissions=self.permissions or [])
        if self.country_office:
            UserRole.objects.get_or_create(
                country_office=self.country_office, program=self.program, user=self.user, group=self.group
            )
        return self

    def __exit__(self, e_typ, e_val, trcbak):
        if self.group:
            self.user.groups.remove(self.group)
            self.group.delete()
        for k, v in self.pre.items():
            setattr(self.user, k, v)
            self.user.save()

        if e_typ:
            raise e_val.with_traceback(trcbak)

    def start(self):
        """Activate a patch, returning any created mock."""
        return self.__enter__()

    def stop(self):
        """Stop an active patch."""
        return self.__exit__(None, None, None)
