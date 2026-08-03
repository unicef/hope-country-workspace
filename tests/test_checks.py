from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from country_workspace.checks import storages_check


if TYPE_CHECKING:
    from django.core.checks import CheckMessage
    from pytest_django.fixtures import SettingsWrapper


@pytest.fixture
def valid_storages(tmp_path: Path) -> dict[str, dict]:
    fs_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": str(tmp_path)}}
    return {
        "default": dict(fs_storage),
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage", "OPTIONS": {}},
        "media": dict(fs_storage),
        "hope": dict(fs_storage),
    }


def _error_ids(messages: list["CheckMessage"]) -> set[str]:
    return {message.id for message in messages}


class _FakeAzureBlobClient:
    def __init__(self, exists_error: Exception | None = None) -> None:
        self._exists_error = exists_error

    def exists(self) -> bool:
        if self._exists_error is not None:
            raise self._exists_error
        return True


class _FakeAzureStorage:
    """Stands in for storages.backends.azure_storage.AzureStorage so the Azure-specific
    branch of _check_azure_backend can be exercised without calling the real Azure API."""

    __module__ = "storages.backends.azure_storage.fake"

    def __init__(self, **options: object) -> None:
        self.overwrite_files = bool(options.get("overwrite_files", False))
        self.client = _FakeAzureBlobClient(exists_error=options.get("exists_error"))


def test_storages_check_reports_error_when_alias_not_configured(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    del valid_storages["hope"]
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    assert "country_workspace.storages.E001.hope" in _error_ids(errors)


def test_storages_check_reports_error_when_backend_is_invalid(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    valid_storages["hope"]["BACKEND"] = "country_workspace.does.not.exist.FakeStorage"
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    assert "country_workspace.storages.E006.hope" in _error_ids(errors)


def test_storages_check_reports_error_when_generic_backend_construction_fails(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    valid_storages["hope"]["OPTIONS"] = {"not_a_real_option": "x"}
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    assert "country_workspace.storages.E005.hope" in _error_ids(errors)


def test_storages_check_warns_when_hope_is_not_azure_backed(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    ids = _error_ids(errors)
    assert "country_workspace.storages.W001" in ids
    assert "country_workspace.storages.E001.hope" not in ids


def test_storages_check_reports_error_when_azure_options_are_empty(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    valid_storages["hope"]["BACKEND"] = f"{__name__}._FakeAzureStorage"
    valid_storages["hope"]["OPTIONS"] = {}
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    assert "country_workspace.storages.E002.hope" in _error_ids(errors)


def test_storages_check_reports_error_when_azure_connection_fails(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    valid_storages["hope"]["BACKEND"] = f"{__name__}._FakeAzureStorage"
    valid_storages["hope"]["OPTIONS"] = {"overwrite_files": True, "exists_error": RuntimeError("boom")}
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    assert "country_workspace.storages.E003.hope" in _error_ids(errors)


def test_storages_check_reports_error_when_hope_azure_backend_does_not_overwrite_files(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    valid_storages["hope"]["BACKEND"] = f"{__name__}._FakeAzureStorage"
    valid_storages["hope"]["OPTIONS"] = {"overwrite_files": False}
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    assert "country_workspace.storages.E004.hope" in _error_ids(errors)


def test_storages_check_passes_for_valid_azure_backend(
    settings: "SettingsWrapper", valid_storages: dict[str, dict]
) -> None:
    valid_storages["hope"]["BACKEND"] = f"{__name__}._FakeAzureStorage"
    valid_storages["hope"]["OPTIONS"] = {"overwrite_files": True}
    settings.STORAGES = valid_storages

    errors = storages_check(None)

    ids = _error_ids(errors)
    assert not ids & {
        "country_workspace.storages.E002.hope",
        "country_workspace.storages.E003.hope",
        "country_workspace.storages.E004.hope",
        "country_workspace.storages.W001",
    }
