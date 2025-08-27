from functools import cache
from typing import Any, Final
from urllib.parse import urlparse

from django.db.models import Model

from country_workspace.admin.sync import Stats
from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.models import Project, Registration
from country_workspace.contrib.hope.sync.base import (
    ParamDateName,
    SyncConfig,
    SkipRecordError,
    sync_entity,
    build_endpoint,
)

MODELS: Final[tuple[type[Model], ...]] = (Project, Registration)
"""List of models to synchronize."""


def _extract_related_id(url: str) -> int | None:
    """Extract the related object ID from the given URL.

    Args:
        url (str): A URL string that is expected to end with the object's ID as its last path segment.

    Returns:
        int | None: The extracted ID if successful, otherwise None.

    """
    parsed_url = urlparse(url)
    try:
        related_id = parsed_url.path.rstrip("/").split("/")[-1]
        return int(related_id)
    except (ValueError, IndexError):
        return None


@cache
def get_aurora_client() -> AuroraClient:
    return AuroraClient()


def sync_projects(delta_sync: bool = False) -> Stats:
    """Fetch and process Project records from the Aurora system."""
    return sync_entity(
        SyncConfig(
            model=Project,
            reference_id="reference_pk",
            endpoint=build_endpoint("project", Project, ParamDateName.MODIFIED, delta_sync),
            prepare_defaults=lambda r: {"name": r["name"]},
            delta_sync=delta_sync,
        ),
        get_aurora_client(),
    )


def sync_registrations(delta_sync: bool = False) -> Stats:
    """Fetch and process Registration records from the Aurora system."""

    def _prepare_defaults(rec: dict[str, Any]) -> dict[str, Any] | None:
        if (extracted_id := _extract_related_id(rec["project"])) is None:
            raise SkipRecordError("Invalid project URL format.")
        try:
            project = Project.objects.get(reference_pk=extracted_id)
        except Project.DoesNotExist as e:
            raise SkipRecordError("Project not found.") from e
        return {
            "name": rec["name"],
            "project": project,
            "reference_pk": rec["id"],
        }

    return sync_entity(
        SyncConfig(
            model=Registration,
            reference_id="reference_pk",
            endpoint=build_endpoint("registration", Registration, ParamDateName.MODIFIED, delta_sync),
            prepare_defaults=_prepare_defaults,
            delta_sync=delta_sync,
        ),
        get_aurora_client(),
    )
