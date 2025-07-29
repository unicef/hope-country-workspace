import os
import random
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from constance.test import override_config
from django.core.management import call_command
from pytest_mock import MockerFixture
from responses import RequestsMock

from country_workspace.management.commands.sync import Command as SyncCommand, run_program_sync, run_geo_sync

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from country_workspace.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def environment() -> dict[str, str]:
    return {
        "ADMIN_EMAIL": "test@example.com",
        "ADMIN_PASSWORD": "test",
        "ALLOWED_HOSTS": "test",
        "AURORA_API_TOKEN": "test",
        "CSRF_COOKIE_SECURE": "test",
        "CSRF_TRUSTED_ORIGINS": "http://testserver/,",
        "HOPE_API_TOKEN": "test",
        "CELERY_BROKER_URL": "",
        "CACHE_URL": "",
        "DATABASE_URL": "",
        "SECRET_KEY": "",
        "MEDIA_ROOT": "/tmp/media",
        "STATIC_ROOT": "/tmp/static",
        "DJANGO_SETTINGS_MODULE": "country_workspace.config.settings",
        "SECURE_SSL_REDIRECT": "1",
        "SESSION_COOKIE_SECURE": "1",
    }


@pytest.mark.parametrize("static_root", ["static", ""], ids=["static_missing", "static_existing"])
@pytest.mark.parametrize("static", [True, False], ids=["static", "no-static"])
@pytest.mark.parametrize("verbosity", [1, 0], ids=["verbose", ""])
@pytest.mark.parametrize("migrate", [True, False], ids=["migrate", ""])
@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_upgrade_init(
    mocker: MockerFixture,
    verbosity: int,
    migrate: bool,
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
    mocker.patch.dict(os.environ, environment, clear=True)
    call_command(
        "upgrade",
        static=static,
        admin_email="user@test.com",
        admin_password="123",
        migrate=migrate,
        stdout=out,
        checks=False,
        verbosity=verbosity,
    )
    assert "error" not in str(out.getvalue())


@pytest.mark.parametrize("verbosity", [1, 0], ids=["verbose", ""])
@pytest.mark.parametrize("migrate", [1, 0], ids=["migrate", ""])
@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_upgrade(verbosity: int, migrate: int, mocker: MockerFixture, environment: dict[str, str]) -> None:
    from testutils.factories import SuperUserFactory

    out = StringIO()
    SuperUserFactory()
    mocker.patch.dict(os.environ, environment, clear=True)
    call_command("upgrade", stdout=out, checks=False, verbosity=verbosity, sync_with_hope=False)
    assert "error" not in str(out.getvalue())


@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_upgrade_next(mocked_responses: RequestsMock) -> None:
    from testutils.factories import SuperUserFactory

    SuperUserFactory()
    out = StringIO()
    call_command("upgrade", stdout=out, checks=False, sync_with_hope=False)
    assert "error" not in str(out.getvalue())


@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_upgrade_check(
    mocker: MockerFixture, mocked_responses: RequestsMock, admin_user: "User", environment: dict[str, str]
) -> None:
    out = StringIO()
    mocker.patch.dict(os.environ, environment, clear=True)
    call_command("upgrade", stdout=out, checks=True, sync_with_hope=False)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("admin", [True, False], ids=["existing_admin", "new_admin"])
def test_upgrade_admin(
    mocker: MockerFixture, mocked_responses: RequestsMock, environment: dict[str, str], admin: str
) -> None:
    from testutils.factories import SuperUserFactory

    if admin:
        email = SuperUserFactory().email
    else:
        email = "new-@example.com"

    out = StringIO()
    mocker.patch.dict(os.environ, environment, clear=True)
    call_command("upgrade", stdout=out, checks=True, admin_email=email, sync_with_hope=False)


@pytest.mark.django_db(transaction=True)
@pytest.mark.xdist_group("remote")
def test_upgrade_sync(mocker: MockerFixture, environment: dict[str, str]) -> None:
    out = StringIO()
    mocker.patch.dict(os.environ, environment, clear=True)
    handle_mock = mocker.patch.object(SyncCommand, "handle")
    handle_mock.return_value = None
    call_command("upgrade", stdout=out, sync_with_hope=True, migrate=False, static=False, prompt=False, checks=False)
    handle_mock.assert_called_once()


def test_run_program_sync(mocker: MockerFixture) -> None:
    sync_offices_mock = mocker.patch("country_workspace.management.commands.sync.sync_offices")
    sync_beneficiary_groups_mock = mocker.patch("country_workspace.management.commands.sync.sync_beneficiary_groups")
    sync_programs_mock = mocker.patch("country_workspace.management.commands.sync.sync_programs")

    run_program_sync()

    sync_offices_mock.assert_called_once()
    sync_beneficiary_groups_mock.assert_called_once()
    sync_programs_mock.assert_called_once()


def test_run_geo_sync(mocker: MockerFixture) -> None:
    sync_countries_mock = mocker.patch("country_workspace.management.commands.sync.sync_countries")
    sync_area_types_mock = mocker.patch("country_workspace.management.commands.sync.sync_area_types")
    sync_areas_mock = mocker.patch("country_workspace.management.commands.sync.sync_areas")

    run_geo_sync()

    sync_countries_mock.assert_called_once()
    sync_area_types_mock.assert_called_once()
    sync_areas_mock.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.xdist_group("remote")
@pytest.mark.parametrize(
    ("cli_args", "run_program_sync_expected", "run_geo_sync_expected"),
    [
        ([], True, True),
        (["--only-context-programs"], True, False),
        (["--only-context-geo"], False, True),
    ],
)
def test_sync(
    mocker: MockerFixture,
    environment: dict[str, str],
    cli_args: list[str],
    run_program_sync_expected: bool,
    run_geo_sync_expected: bool,
) -> None:
    out = StringIO()
    run_program_sync = mocker.patch("country_workspace.management.commands.sync.run_program_sync")
    run_geo_sync_mock = mocker.patch("country_workspace.management.commands.sync.run_geo_sync")

    call_command("sync", *cli_args, stdout=out)

    assert run_program_sync.call_count == run_program_sync_expected
    assert run_geo_sync_mock.call_count == run_geo_sync_expected
