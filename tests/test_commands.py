import os
import random
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from django.core.management import call_command

import pytest
from pytest import MonkeyPatch
from responses import RequestsMock
from testutils.factories import SuperUserFactory

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from country_workspace.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture()
def environment() -> dict[str, str]:
    return {
        "CACHE_URL": "test",
        "CELERY_BROKER_URL": "",
        "DATABASE_URL": "",
        "SECRET_KEY": "",
        "MEDIA_ROOT": "/tmp/media",
        "STATIC_ROOT": "/tmp/static",
        "SECURE_SSL_REDIRECT": "1",
        "SESSION_COOKIE_SECURE": "1",
    }


@pytest.mark.parametrize(
    "static_root", ["static", ""], ids=["static_missing", "static_existing"]
)
@pytest.mark.parametrize("static", [True, False], ids=["static", "no-static"])
@pytest.mark.parametrize("verbosity", [1, 0], ids=["verbose", ""])
@pytest.mark.parametrize("migrate", [True, False], ids=["migrate", ""])
def test_upgrade_init(
    verbosity: int,
    migrate: bool,
    monkeypatch: MonkeyPatch,
    environment: dict[str, str],
    static: bool,
    static_root: str,
    tmp_path: Path,
    settings: "SettingsWrapper",
) -> None:
    if static_root:
        static_root_path = tmp_path / static_root
        static_root_path.mkdir()
    else:
        static_root_path = tmp_path / str(random.randint(1, 10000))
        assert not Path(static_root_path).exists()
    out = StringIO()
    settings.STATIC_ROOT = str(static_root_path.absolute())
    with mock.patch.dict(
        os.environ,
        {**environment, "STATIC_ROOT": str(static_root_path.absolute())},
        clear=True,
    ):
        call_command(
            "upgrade",
            static=static,
            admin_email="user@test.com",
            admin_password="123",
            migrate=migrate,
            stdout=out,
            check=False,
            verbosity=verbosity,
        )
    assert "error" not in str(out.getvalue())


@pytest.mark.parametrize("verbosity", [1, 0], ids=["verbose", ""])
@pytest.mark.parametrize("migrate", [1, 0], ids=["migrate", ""])
def test_upgrade(
    verbosity: int, migrate: int, monkeypatch: MonkeyPatch, environment: dict[str, str]
) -> None:
    from testutils.factories import SuperUserFactory

    out = StringIO()
    SuperUserFactory()
    with mock.patch.dict(os.environ, environment, clear=True):
        call_command("upgrade", stdout=out, check=False, verbosity=verbosity)
    assert "error" not in str(out.getvalue())


def test_upgrade_next(mocked_responses: RequestsMock) -> None:
    SuperUserFactory()
    out = StringIO()
    call_command("upgrade", stdout=out, check=False)
    assert "error" not in str(out.getvalue())


def test_upgrade_check(
    mocked_responses: RequestsMock, admin_user: "User", environment: dict[str, str]
) -> None:
    out = StringIO()
    with mock.patch.dict(os.environ, environment, clear=True):
        call_command("upgrade", stdout=out, check=True)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("admin", [True, False], ids=["existing_admin", "new_admin"])
def test_upgrade_admin(
    mocked_responses: RequestsMock, environment: dict[str, str], admin: str
) -> None:
    if admin:
        email = SuperUserFactory().email
    else:
        email = "new-@example.com"

    out = StringIO()
    with mock.patch.dict(os.environ, environment, clear=True):
        call_command("upgrade", stdout=out, check=True, admin_email=email)
