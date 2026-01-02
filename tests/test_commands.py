import os
import random
import re
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from constance.test import override_config
from django.core.management import call_command
from pytest_mock import MockerFixture
from responses import RequestsMock

from country_workspace.management.commands.sync import Command as SyncCommand, run_program_sync, run_geo_sync
import country_workspace.management.commands.gen_rdi as gen_rdi_cmd
from country_workspace.utils.gen_rdi import GenerationMode, GeneratorConfig
import country_workspace.management.commands.upgrade as upgrade_cmd

from testutils.factories import SuperUserFactory, UserFactory


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
    out = StringIO()
    SuperUserFactory()
    mocker.patch.dict(os.environ, environment, clear=True)
    call_command("upgrade", stdout=out, checks=False, verbosity=verbosity, sync_with_hope=False)
    assert "error" not in str(out.getvalue())


@override_config(HOPE_API_URL="https://dev-hope.unitst.org/api/rest/")
def test_upgrade_next(mocked_responses: RequestsMock) -> None:
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


@pytest.mark.parametrize(
    ("cli_args", "expect"),
    [
        # PEOPLE mode
        (
            [
                "afghanistan",
                "-P",
                "5",
                "-L",
                "en_US",
                "-S",
                "42",
                "-o",
                "out.xlsx",
                "-X",
                "wallet_address, email",
                "-X",
                "phone_no",
            ],
            {
                "mode": GenerationMode.PEOPLE,
                "office": "afghanistan",
                "people": 5,
                "locale": "en_US",
                "seed": 42,
                "filename": "out.xlsx",
                "exclude": ("wallet_address", "email", "phone_no"),
            },
        ),
        # HH_IND mode
        (
            ["afghanistan", "-H", "3", "--inds-min", "2", "--inds-max", "4", "-L", "en_US", "-S", "7"],
            {
                "mode": GenerationMode.HH_IND,
                "office": "afghanistan",
                "hh": 3,
                "inds": (2, 4),
                "locale": "en_US",
                "seed": 7,
                "filename": None,
                "exclude": (),
            },
        ),
    ],
)
def test_gen_rdi_happy_paths(mocker: MockerFixture, cli_args: list[str], expect: dict[str, any]) -> None:
    """Smoke test: CLI builds GeneratorConfig and calls generate once."""
    out = StringIO()
    gen = mocker.patch.object(gen_rdi_cmd, "generate", return_value="used.xlsx")

    call_command("gen_rdi", *cli_args, stdout=out)

    # called once with GeneratorConfig instance
    assert gen.call_count == 1
    (cfg,), _ = gen.call_args
    assert isinstance(cfg, GeneratorConfig)

    # core expectations by mode
    assert cfg.mode is expect["mode"]
    assert cfg.office_slug == expect["office"]
    assert cfg.locale == expect["locale"]
    assert cfg.seed == expect["seed"]
    assert cfg.filename == expect["filename"]

    if cfg.mode is GenerationMode.PEOPLE:
        assert cfg.people == expect["people"]
    else:
        assert cfg.hh_amount == expect["hh"]
        assert cfg.inds_per_hh == expect["inds"]

    assert tuple(cfg.exclude_fields) == expect["exclude"]

    s = out.getvalue()
    assert "RDI file 'used.xlsx' generated successfully." in s


@pytest.mark.parametrize(
    ("cli_args", "err"),
    [
        (["afghanistan", "-H", "1", "-P", "2"], "Cannot mix HH parameters"),
        (["afghanistan", "-H", "0"], "--households must be > 0"),
        (["afghanistan", "--inds-min", "2"], "Pass both --inds-min and --inds-max"),
        (["afghanistan", "--inds-min", "5", "--inds-max", "3"], "--inds-min must be > 0"),
        (["afghanistan", "-P", "0"], "--people must be > 0"),
    ],
)
def test_gen_rdi_validation_errors(cli_args: list[str], err: str) -> None:
    """Validation errors should raise CommandError with a helpful message."""
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match=re.escape(err)):
        call_command("gen_rdi", *cli_args)


@pytest.mark.parametrize(
    ("factory_key", "kwargs", "expect_changed"),
    [
        ("user", {"is_staff": False, "is_superuser": False}, True),
        ("superuser", {}, False),
    ],
    ids=["promotes", "noop"],
)
def test_upgrade_ensure_superuser(
    mocker: MockerFixture,
    factory_key: str,
    kwargs: dict[str, object],
    expect_changed: bool,
) -> None:
    factory = {"user": UserFactory, "superuser": SuperUserFactory}[factory_key]
    user = factory(**kwargs)
    save_spy = mocker.spy(user, "save")

    assert upgrade_cmd.Command()._ensure_superuser(user) is expect_changed

    if expect_changed:
        assert user.is_staff is True
        assert user.is_superuser is True
        save_spy.assert_called_once_with(update_fields=["is_staff", "is_superuser"])
    else:
        save_spy.assert_not_called()


def test_upgrade_run_createsuperuser_pops_password_env_when_missing(mocker: MockerFixture) -> None:
    cmd = upgrade_cmd.Command()
    cmd.admin_email = "admin@example.com"
    cmd.admin_password = ""
    cmd.verbosity = 1

    call = mocker.patch.object(upgrade_cmd, "call_command")
    mocker.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": "stale"}, clear=True)

    assert cmd._run_createsuperuser("admin@example.com", "admin@example.com") is False
    assert "DJANGO_SUPERUSER_PASSWORD" not in os.environ

    call.assert_called_once_with(
        "createsuperuser",
        email="admin@example.com",
        username="admin@example.com",
        verbosity=0,
        interactive=False,
    )
