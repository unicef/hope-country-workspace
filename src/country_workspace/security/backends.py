from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group

from country_workspace.models import CountryOffice, UserRole

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.contrib.auth.models import AbstractBaseUser


class AnyUserAuthBackend(ModelBackend):
    """DEBUG Only smart auth backend  auto-create users"""

    def authenticate(
        self,
        request: "Optional[HttpRequest]",
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> "AbstractBaseUser | None":
        countries = CountryOffice.objects.values_list("slug", flat=True)

        if settings.DEBUG:
            if username in countries:
                user, __ = get_user_model().objects.update_or_create(
                    username=username,
                    defaults=dict(is_staff=True, is_active=True, is_superuser=False),
                )
                office = CountryOffice.objects.get(slug=username)
                g = Group.objects.get(name=settings.ANALYST_GROUP_NAME)
                UserRole.objects.create(user=user, country_office=office, group=g)
                return user
            elif username in ["admin", "superuser", "administrator", "sax"]:
                user, __ = get_user_model().objects.update_or_create(
                    username=username,
                    defaults=dict(is_staff=True, is_active=True, is_superuser=True),
                )
                return user
        return None
