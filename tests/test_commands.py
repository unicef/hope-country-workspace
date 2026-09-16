import os
import random
import re
from base64 import b64encode
from io import StringIO
from pathlib import Path
from typing import Any, TYPE_CHECKING
from uuid import uuid4

import pytest
from constance.test import override_config
from django.core.management import CommandError, call_command
from pytest_mock import MockerFixture
from responses import RequestsMock

from country_workspace.management.commands.sync import (
    Command as SyncCommand,
    run_flex_fields_sync,
    run_geo_sync,
    run_program_sync,
)
import country_workspace.management.commands.gen_rdi as gen_rdi_cmd
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.utils.gen_rdi import GenerationMode, GeneratorConfig


if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from country_workspace.models import User

pytestmark = pytest.mark.django_db

PHOTO = b"\x89PNG\r\n\x1a\nphoto"


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


@pytest.fixture
def legacy_individual():
    """An individual whose photo is still inline, keyed differently in each payload."""
    from testutils.factories import IndividualFactory

    data_uri = "data:image/png;base64,%s" % b64encode(PHOTO).decode()
    return IndividualFactory(
        flex_fields={"individual_id": "I-1", "photo": data_uri},
        raw_data={"individual_id": "I-1", "beneficiary_photo": data_uri},
    )


def test_migrate_flex_files_converts_inline_data_uris(legacy_individual) -> None:
    out = StringIO()

    call_command("migrate_flex_files", stdout=out)

    legacy_individual.refresh_from_db()
    flex_file = legacy_individual.flex_field_files.get()
    assert legacy_individual.flex_fields["photo"] == flex_file.reference
    assert legacy_individual.raw_data["beneficiary_photo"] == flex_file.reference
    assert legacy_individual.flex_fields["individual_id"] == "I-1"
    assert FlexFieldFile.objects.with_content().get(pk=flex_file.pk).content_bytes == PHOTO
    assert "individual: converted 1 record(s)" in out.getvalue()


def test_migrate_flex_files_leaves_converted_records_alone(legacy_individual) -> None:
    call_command("migrate_flex_files", stdout=StringIO())
    out = StringIO()

    call_command("migrate_flex_files", stdout=out)

    assert legacy_individual.flex_field_files.count() == 1
    assert "individual: converted 0 record(s)" in out.getvalue()


def test_migrate_flex_files_dry_run_writes_nothing(legacy_individual) -> None:
    out = StringIO()

    call_command("migrate_flex_files", "--dry-run", stdout=out)

    legacy_individual.refresh_from_db()
    assert legacy_individual.flex_fields["photo"].startswith("data:image/png;base64,")
    assert not FlexFieldFile.objects.exists()
    assert "[dry-run] individual: converted 1 record(s)" in out.getvalue()


def test_migrate_flex_files_reverse_restores_inline_data_uris(legacy_individual) -> None:
    call_command("migrate_flex_files", stdout=StringIO())
    out = StringIO()

    call_command("migrate_flex_files", "--reverse", stdout=out)

    legacy_individual.refresh_from_db()
    data_uri = "data:image/png;base64,%s" % b64encode(PHOTO).decode()
    assert legacy_individual.flex_fields["photo"] == data_uri
    assert legacy_individual.raw_data["beneficiary_photo"] == data_uri
    assert not FlexFieldFile.objects.exists()
    assert "individual: restored 1 record(s)" in out.getvalue()


@pytest.fixture
def legacy_household():
    """A household whose signature is still inline, on a model --model individual should skip."""
    from testutils.factories import HouseholdFactory

    data_uri = "data:image/png;base64,%s" % b64encode(PHOTO).decode()
    return HouseholdFactory(flex_fields={"consent_sign": data_uri})


def test_migrate_flex_files_model_filter_only_touches_the_given_model(legacy_individual, legacy_household) -> None:
    out = StringIO()

    call_command("migrate_flex_files", "--model", "individual", stdout=out)

    legacy_individual.refresh_from_db()
    legacy_household.refresh_from_db()
    assert FlexFieldFile.is_reference(legacy_individual.flex_fields["photo"])
    assert legacy_household.flex_fields["consent_sign"].startswith("data:image/png;base64,")
    assert "household" not in out.getvalue()


def test_migrate_flex_files_start_pk_requires_an_explicit_model() -> None:
    with pytest.raises(CommandError, match="--start-pk needs an explicit --model"):
        call_command("migrate_flex_files", "--start-pk", "5")


@pytest.fixture
def other_legacy_individual(legacy_individual):
    """A second legacy individual, created after the first so it sorts after it by pk."""
    from testutils.factories import IndividualFactory

    data_uri = "data:image/png;base64,%s" % b64encode(PHOTO).decode()
    return IndividualFactory(flex_fields={"individual_id": "I-2", "photo": data_uri})


def test_migrate_flex_files_limit_stops_early_with_a_resume_hint(legacy_individual, other_legacy_individual) -> None:
    out = StringIO()

    call_command("migrate_flex_files", "--model", "individual", "--limit", "1", stdout=out)

    assert FlexFieldFile.objects.count() == 1
    assert legacy_individual.flex_field_files.exists()
    assert not other_legacy_individual.flex_field_files.exists()
    assert (
        "individual: the limit was reached, resume with --model individual --start-pk %d" % legacy_individual.pk
        in out.getvalue()
    )


def test_migrate_flex_files_continue_on_error_converts_the_rest_and_reports_the_failure(
    legacy_individual, other_legacy_individual, monkeypatch
) -> None:
    import country_workspace.management.commands.migrate_flex_files as module

    original_write = module.write_flex_file

    def flaky_write(record, field_name, content, mimetype=module.DEFAULT_MIMETYPE, filename=""):
        if record.pk == legacy_individual.pk:
            raise ValueError("boom")
        return original_write(record, field_name, content, mimetype, filename)

    monkeypatch.setattr(module, "write_flex_file", flaky_write)
    out = StringIO()

    with pytest.raises(CommandError, match=r"1 record\(s\) failed"):
        call_command("migrate_flex_files", "--model", "individual", "--continue-on-error", stdout=out)

    other_legacy_individual.refresh_from_db()
    assert other_legacy_individual.flex_field_files.exists()
    legacy_individual.refresh_from_db()
    assert legacy_individual.flex_fields["photo"].startswith("data:image/png;base64,")
    assert "failed 1" in out.getvalue()


def test_migrate_flex_files_stops_at_the_first_failure_by_default(
    legacy_individual, other_legacy_individual, monkeypatch
) -> None:
    import country_workspace.management.commands.migrate_flex_files as module

    def flaky_write(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(module, "write_flex_file", flaky_write)
    out = StringIO()

    with pytest.raises(ValueError, match="boom"):
        call_command("migrate_flex_files", "--model", "individual", stdout=out)

    assert not FlexFieldFile.objects.exists()
    assert (
        "individual: #%s failed, resume with --model individual --start-pk %d"
        % (legacy_individual.pk, legacy_individual.pk - 1)
        in out.getvalue()
    )


def test_migrate_flex_files_no_lock_skips_the_concurrency_lock(legacy_individual) -> None:
    out = StringIO()

    call_command("migrate_flex_files", "--no-lock", stdout=out)

    assert "individual: converted 1 record(s)" in out.getvalue()


def test_migrate_flex_files_refuses_to_run_twice_at_once(legacy_individual) -> None:
    from django.core.cache import cache

    from country_workspace.management.commands.migrate_flex_files import LOCK_EXPIRE, LOCK_KEY

    lock = cache.lock(LOCK_KEY, LOCK_EXPIRE)
    lock.acquire(blocking=False)
    try:
        with pytest.raises(CommandError, match="another migrate_flex_files run is in progress"):
            call_command("migrate_flex_files", stdout=StringIO())
    finally:
        lock.release()


@pytest.fixture
def individual_with_garbled_data_uri():
    """A value that looks like a data-URI but does not decode as base64."""
    from testutils.factories import IndividualFactory

    return IndividualFactory(flex_fields={"individual_id": "I-3", "photo": "data:image/png;base64,not-base64!!"})


def test_migrate_flex_files_skips_an_unreadable_data_uri(individual_with_garbled_data_uri) -> None:
    out = StringIO()

    call_command("migrate_flex_files", stdout=out)

    individual_with_garbled_data_uri.refresh_from_db()
    assert individual_with_garbled_data_uri.flex_fields["photo"] == "data:image/png;base64,not-base64!!"
    assert not FlexFieldFile.objects.exists()
    assert "individual: converted 0 record(s)" in out.getvalue()
    assert "unreadable 1" in out.getvalue()


def test_migrate_flex_files_reverse_skips_a_reference_without_a_row(legacy_individual) -> None:
    call_command("migrate_flex_files", stdout=StringIO())
    legacy_individual.refresh_from_db()
    dangling = "flexfile:%s" % uuid4()
    legacy_individual.flex_fields["extra"] = dangling
    legacy_individual.save(update_fields=["flex_fields"])

    out = StringIO()
    call_command("migrate_flex_files", "--reverse", stdout=out)

    legacy_individual.refresh_from_db()
    assert legacy_individual.flex_fields["extra"] == dangling
    assert "unreadable 1" in out.getvalue()


def test_migrate_flex_files_reverse_drops_rows_of_a_deleted_owner() -> None:
    """Rows left by a record deleted outside the cascade are swept on --reverse."""
    from django.contrib.contenttypes.models import ContentType

    from country_workspace.models import Individual

    orphan = FlexFieldFile.objects.create(
        content_type=ContentType.objects.get_for_model(Individual),
        object_id=999_999,
        field_name="photo",
        content=PHOTO,
        mimetype="image/png",
        size=len(PHOTO),
        checksum="deadbeef",
    )

    dry_out = StringIO()
    call_command("migrate_flex_files", "--reverse", "--model", "individual", "--dry-run", stdout=dry_out)
    assert FlexFieldFile.objects.filter(pk=orphan.pk).exists()
    assert "orphan row(s) dropped" in dry_out.getvalue()

    out = StringIO()
    call_command("migrate_flex_files", "--reverse", "--model", "individual", stdout=out)
    assert not FlexFieldFile.objects.filter(pk=orphan.pk).exists()
    assert "orphan row(s) dropped" in out.getvalue()
