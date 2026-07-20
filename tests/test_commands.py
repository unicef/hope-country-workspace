import os
import random
import re
from io import StringIO
from pathlib import Path
from typing import Any, TYPE_CHECKING

import pytest
from azure.core.exceptions import AzureError, ResourceExistsError
from constance.test import override_config
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command, CommandError
from pytest_mock import MockerFixture
from responses import RequestsMock

from country_workspace.management.commands.sync import (
    Command as SyncCommand,
    run_flex_fields_sync,
    run_geo_sync,
    run_program_sync,
)
import country_workspace.management.commands.gen_rdi as gen_rdi_cmd
from country_workspace.utils.gen_rdi import GenerationMode, GeneratorConfig


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


@pytest.mark.parametrize("delta_sync", [False, True])
def test_run_program_sync(mocker: MockerFixture, delta_sync: bool) -> None:
    offices_stats = {"add": 1, "upd": 2, "errors": []}
    bg_stats = {"add": 0, "upd": 0, "errors": []}
    programs_stats = {"add": 3, "upd": 4, "errors": []}
    sync_offices_mock = mocker.patch(
        "country_workspace.management.commands.sync.sync_offices", return_value=offices_stats
    )
    sync_beneficiary_groups_mock = mocker.patch(
        "country_workspace.management.commands.sync.sync_beneficiary_groups", return_value=bg_stats
    )
    sync_programs_mock = mocker.patch(
        "country_workspace.management.commands.sync.sync_programs", return_value=programs_stats
    )

    result = run_program_sync(delta_sync=delta_sync)

    sync_offices_mock.assert_called_once_with(delta_sync=delta_sync)
    sync_beneficiary_groups_mock.assert_called_once_with(delta_sync=delta_sync)
    sync_programs_mock.assert_called_once_with(delta_sync=delta_sync)
    assert result == {"offices": offices_stats, "beneficiary_groups": bg_stats, "programs": programs_stats}


@pytest.mark.parametrize("delta_sync", [False, True])
def test_run_geo_sync(mocker: MockerFixture, delta_sync: bool) -> None:
    countries_stats = {"add": 1, "upd": 0, "errors": []}
    area_types_stats = {"add": 0, "upd": 2, "errors": []}
    areas_stats = {"add": 5, "upd": 1, "errors": []}
    sync_countries_mock = mocker.patch(
        "country_workspace.management.commands.sync.sync_countries", return_value=countries_stats
    )
    sync_area_types_mock = mocker.patch(
        "country_workspace.management.commands.sync.sync_area_types", return_value=area_types_stats
    )
    sync_areas_mock = mocker.patch("country_workspace.management.commands.sync.sync_areas", return_value=areas_stats)

    result = run_geo_sync(delta_sync=delta_sync)

    sync_countries_mock.assert_called_once_with(delta_sync=delta_sync)
    sync_area_types_mock.assert_called_once_with(delta_sync=delta_sync)
    sync_areas_mock.assert_called_once_with(delta_sync=delta_sync)
    assert result == {"countries": countries_stats, "area_types": area_types_stats, "areas": areas_stats}


def test_run_flex_fields_sync(mocker: MockerFixture) -> None:
    refresh = mocker.patch("country_workspace.management.commands.sync.SyncLog.objects.refresh", return_value=7)

    result = run_flex_fields_sync()

    refresh.assert_called_once_with()
    assert result == {"refreshed": 7}


@pytest.mark.django_db(transaction=True)
@pytest.mark.xdist_group("remote")
@pytest.mark.parametrize(
    (
        "cli_args",
        "run_program_sync_expected",
        "run_geo_sync_expected",
        "run_flex_fields_sync_expected",
        "delta_expected",
    ),
    [
        ([], 1, 1, 1, False),
        (["--only-context-programs"], 1, 0, 0, False),
        (["--only-context-geo"], 0, 1, 0, False),
        (["--only-flex-fields"], 0, 0, 1, False),
        (["--delta"], 1, 1, 1, True),
    ],
)
def test_sync(
    mocker: MockerFixture,
    environment: dict[str, str],
    cli_args: list[str],
    run_program_sync_expected: int,
    run_geo_sync_expected: int,
    run_flex_fields_sync_expected: int,
    delta_expected: bool,
) -> None:
    out = StringIO()
    run_program_sync_mock = mocker.patch("country_workspace.management.commands.sync.run_program_sync")
    run_geo_sync_mock = mocker.patch("country_workspace.management.commands.sync.run_geo_sync")
    run_flex_fields_sync_mock = mocker.patch("country_workspace.management.commands.sync.run_flex_fields_sync")

    call_command("sync", *cli_args, stdout=out)

    assert run_program_sync_mock.call_count == run_program_sync_expected
    assert run_geo_sync_mock.call_count == run_geo_sync_expected
    assert run_flex_fields_sync_mock.call_count == run_flex_fields_sync_expected
    if run_program_sync_expected:
        run_program_sync_mock.assert_called_with(delta_sync=delta_expected)
    if run_geo_sync_expected:
        run_geo_sync_mock.assert_called_with(delta_sync=delta_expected)


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
                "with_postfix": False,
                "image_dir": None,
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
                "with_postfix": False,
                "image_dir": None,
            },
        ),
        (
            [
                "afghanistan",
                "-P",
                "2",
                "--with-postfix",
                "--image-dir",
                "/tmp/images",
            ],
            {
                "mode": GenerationMode.PEOPLE,
                "office": "afghanistan",
                "people": 2,
                "locale": "en",
                "seed": None,
                "filename": None,
                "exclude": (),
                "with_postfix": True,
                "image_dir": "/tmp/images",
            },
        ),
    ],
)
def test_gen_rdi_happy_paths(mocker: MockerFixture, cli_args: list[str], expect: dict[str, Any]) -> None:
    out = StringIO()
    gen = mocker.patch.object(gen_rdi_cmd, "generate", return_value="used.xlsx")

    call_command("gen_rdi", *cli_args, stdout=out)

    assert gen.call_count == 1
    (cfg,), _ = gen.call_args
    assert isinstance(cfg, GeneratorConfig)

    assert cfg.mode is expect["mode"]
    assert cfg.office_slug == expect["office"]
    assert cfg.locale == expect["locale"]
    assert cfg.seed == expect["seed"]
    assert cfg.filename == expect["filename"]
    assert tuple(cfg.exclude_fields) == expect["exclude"]
    assert cfg.with_postfix is expect.get("with_postfix", False)
    assert cfg.image_dir == expect.get("image_dir")

    if cfg.mode is GenerationMode.PEOPLE:
        assert cfg.people == expect["people"]
    else:
        assert cfg.hh_amount == expect["hh"]
        assert cfg.inds_per_hh == expect["inds"]

    assert "RDI file 'used.xlsx' generated successfully." in out.getvalue()


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


class _FakeAzureStorage:
    def __init__(self, client: Any) -> None:
        self.client = client


@pytest.fixture
def hope_storage(mocker: MockerFixture):
    def _patch(storage: Any) -> Any:
        mocker.patch("country_workspace.management.commands.init_hope_storage.storages", {"hope": storage})
        return storage

    return _patch


def test_init_hope_storage_skips_non_azure_backend(hope_storage, tmp_path: Path) -> None:
    hope_storage(FileSystemStorage(location=str(tmp_path)))
    out = StringIO()

    call_command("init_hope_storage", stdout=out)

    assert "not an Azure backend" in out.getvalue()


def test_init_hope_storage_creates_container(hope_storage, mocker: MockerFixture) -> None:
    client = mocker.Mock()
    hope_storage(_FakeAzureStorage(client))
    out = StringIO()

    call_command("init_hope_storage", stdout=out)

    client.create_container.assert_called_once_with()
    assert "Created HOPE blob container" in out.getvalue()


def test_init_hope_storage_handles_existing_container(hope_storage, mocker: MockerFixture) -> None:
    client = mocker.Mock()
    client.create_container.side_effect = ResourceExistsError("already there")
    hope_storage(_FakeAzureStorage(client))
    out = StringIO()

    call_command("init_hope_storage", stdout=out)

    assert "already exists" in out.getvalue()


def test_init_hope_storage_raises_command_error_on_azure_failure(hope_storage, mocker: MockerFixture) -> None:
    client = mocker.Mock()
    client.create_container.side_effect = AzureError("boom")
    hope_storage(_FakeAzureStorage(client))

    with pytest.raises(CommandError, match="Failed to create HOPE blob container"):
        call_command("init_hope_storage")
