from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Warning as CheckWarning, register
from django.utils.module_loading import import_string

STORAGE_ALIASES = ("hope", "staticfiles", "media")


@register(deploy=True)
def storages_check(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []

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

        backend_path = config.get("BACKEND")
        options = config.get("OPTIONS", {})
        backend = import_string(backend_path)

        if backend.__module__.startswith("storages.backends.azure_storage"):
            if not options:
                errors.append(
                    Error(
                        f"STORAGES['{alias}'] uses AzureStorage but has empty OPTIONS.",
                        hint=f"Set the full FILE_STORAGE_{alias.upper()} URL with connection params.",
                        id=f"country_workspace.storages.E002.{alias}",
                    )
                )
                continue
            try:
                storage = backend(**options)
                storage.client.exists()
            except Exception as e:  # noqa: BLE001
                errors.append(
                    Error(
                        f"STORAGES['{alias}'] could not connect to Azure: {e}",
                        hint="Verify account credentials, container name, and network access.",
                        id=f"country_workspace.storages.E003.{alias}",
                    )
                )
                continue
            # blob sync (hope_blob.py) saves images under deterministic keys and relies on
            # save() overwriting existing blobs instead of renaming them.
            if alias == "hope" and not getattr(storage, "overwrite_files", False):
                errors.append(
                    Error(
                        "STORAGES['hope'] must be configured with overwrite_files=True.",
                        hint="Append 'overwrite_files=True' to the FILE_STORAGE_HOPE URL.",
                        id="country_workspace.storages.E004.hope",
                    )
                )

    hope = settings.STORAGES.get("hope", {})
    if hope and not import_string(hope["BACKEND"]).__module__.startswith("storages.backends.azure_storage"):
        errors.append(
            CheckWarning(
                "STORAGES['hope'] is not backed by Azure blob storage.",
                hint="Set FILE_STORAGE_HOPE to storages.backends.azure_storage.AzureStorage in deployed environments.",
                id="country_workspace.storages.W001",
            )
        )

    return errors
