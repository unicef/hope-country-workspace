from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group

from country_workspace.models import Office, UserRole

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.http import HttpRequest


class AnyUserAuthBackend(ModelBackend):
    """DEBUG Only smart auth backend  auto-create users."""

    def authenticate(
        self,
        request: "HttpRequest | None",
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> "AbstractBaseUser | None":
        offices = Office.objects.values_list("slug", flat=True)

        if settings.DEBUG:
            if username in offices:
                user, __ = get_user_model().objects.update_or_create(
                    username=username,
                    defaults={"is_staff": True, "is_active": True, "is_superuser": False},
                )
                office = Office.objects.get(slug=username)
                g = Group.objects.get(name=settings.ANALYST_GROUP_NAME)
                UserRole.objects.get_or_create(user=user, country_office=office, group=g)
                return user
            if username in ["admin", "superuser", "administrator", "sax"]:
                user, __ = get_user_model().objects.update_or_create(
                    username=username,
                    defaults={"is_staff": True, "is_active": True, "is_superuser": True},
                )
                return user
            if username == "staff":
                user, __ = get_user_model().objects.update_or_create(
                    username=username,
                    defaults={"is_staff": True, "is_active": True, "is_superuser": False},
                )
                return user
        return None
