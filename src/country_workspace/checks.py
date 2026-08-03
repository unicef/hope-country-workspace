from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Warning as CheckWarning, register
from django.utils.module_loading import import_string

STORAGE_ALIASES = ("hope", "staticfiles", "media")


def _check_azure_backend(alias: str, backend: type, options: dict) -> list[CheckMessage]:
    if not options:
        return [
            Error(
                f"STORAGES['{alias}'] uses AzureStorage but has empty OPTIONS.",
                hint=f"Set the full FILE_STORAGE_{alias.upper()} URL with connection params.",
                id=f"country_workspace.storages.E002.{alias}",
            )
        ]

    try:
        storage = backend(**options)
        storage.client.exists()
    except Exception as e:  # noqa: BLE001
        return [
            Error(
                f"STORAGES['{alias}'] could not connect to Azure: {e}",
                hint="Verify account credentials, container name, and network access.",
                id=f"country_workspace.storages.E003.{alias}",
            )
        ]

    # blob sync (hope_blob.py) saves images under deterministic keys and relies on
    # save() overwriting existing blobs instead of renaming them.
    if alias == "hope" and not getattr(storage, "overwrite_files", False):
        return [
            Error(
                "STORAGES['hope'] must be configured with overwrite_files=True.",
                hint="Append 'overwrite_files=True' to the FILE_STORAGE_HOPE URL.",
                id="country_workspace.storages.E004.hope",
            )
        ]
    return []


def _check_generic_backend(alias: str, backend: type, options: dict) -> list[CheckMessage]:
    # HOPE_STORAGE/MEDIA_STORAGE resolve lazily (see storages.py), so a bad BACKEND
    # or OPTIONS would otherwise go unnoticed until the first real save/open in
    # production. Constructing eagerly here restores that fail-fast behaviour.
    try:
        backend(**options)
    except Exception as e:  # noqa: BLE001
        return [
            Error(
                f"STORAGES['{alias}'] could not be constructed: {e}",
                hint=f"Verify BACKEND and OPTIONS for STORAGES['{alias}'].",
                id=f"country_workspace.storages.E005.{alias}",
            )
        ]
    return []


def _check_storage_backend(alias: str, config: dict) -> tuple[list[CheckMessage], type | None]:
    backend_path = config.get("BACKEND")
    options = config.get("OPTIONS", {})
    try:
        backend = import_string(backend_path)
    except Exception as e:  # noqa: BLE001
        errors: list[CheckMessage] = [
            Error(
                f"STORAGES['{alias}']['BACKEND'] is invalid: {e}",
                hint=f"Check the BACKEND path configured for STORAGES['{alias}'].",
                id=f"country_workspace.storages.E006.{alias}",
            )
        ]
        return errors, None

    if backend.__module__.startswith("storages.backends.azure_storage"):
        return _check_azure_backend(alias, backend, options), backend
    return _check_generic_backend(alias, backend, options), backend


@register(deploy=True)
def storages_check(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    hope_backend: type | None = None

    for alias in STORAGE_ALIASES:
        config = settings.STORAGES.get(alias)
        if not config:
            errors.append(
                Error(
                    f"STORAGES['{alias}'] is not configured.",
                    id=f"country_workspace.storages.E001.{alias}",
                )
            )
            continue

        alias_errors, backend = _check_storage_backend(alias, config)
        errors.extend(alias_errors)
        if alias == "hope":
            hope_backend = backend

    if hope_backend and not hope_backend.__module__.startswith("storages.backends.azure_storage"):
        errors.append(
            CheckWarning(
                "STORAGES['hope'] is not backed by Azure blob storage.",
                hint="Set FILE_STORAGE_HOPE to storages.backends.azure_storage.AzureStorage in deployed environments.",
                id="country_workspace.storages.W001",
            )
        )

    return errors
