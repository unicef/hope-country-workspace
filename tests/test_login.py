from typing import TYPE_CHECKING

from django.urls import reverse

import pytest
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from responses import RequestsMock

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from pytest_django.fixtures import SettingsWrapper

pytestmark = [pytest.mark.django_db]


@pytest.fixture()
def app(
    django_app_factory: "MixinWithInstanceVariables",
    mocked_responses: "RequestsMock",
    settings: "SettingsWrapper",
) -> "DjangoTestApp":
    from testutils.factories import UserFactory

    settings.SUPERUSERS = ["superuser"]
    UserFactory(username="superuser", is_staff=False, is_superuser=False)
    UserFactory(username="user", is_staff=False, is_superuser=False)
    django_app = django_app_factory(csrf_checks=False)
    yield django_app


def test_login_enable_superuser(app: "DjangoTestApp") -> None:
    from country_workspace.models import User

    url = reverse("workspace:login")
    res = app.get(url)
    res.forms["login-form"]["username"] = "superuser"
    res.forms["login-form"]["password"] = "password"
    res.forms["login-form"].submit().follow()
    # check the pipeline
    assert User.objects.filter(
        is_staff=True,
        is_superuser=True,
        is_active=True,
        username="superuser",
    ).exists()


def test_login_usse(app: "DjangoTestApp") -> None:
    from country_workspace.models import User

    url = reverse("workspace:login")
    res = app.get(url)
    res.forms["login-form"]["username"] = "user"
    res.forms["login-form"]["password"] = "password"
    res.forms["login-form"].submit().follow()
    # check the pipeline
    assert User.objects.filter(
        is_staff=False,
        is_superuser=False,
        is_active=True,
        username="user",
    ).exists()
