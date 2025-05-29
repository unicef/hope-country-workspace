from typing import Any, Final
from enum import auto
from dataclasses import dataclass, field
from io import TextIOBase
from django.db.models import Model
from urllib.parse import urlparse

from country_workspace.contrib.aurora.models import Project, Registration
from country_workspace.contrib.hope.sync.base import (
    BaseSync,
    BaseSyncStep,
    SyncConfig,
    EndpointConfig,
    sync_context,
    SkipRecordError,
)
from country_workspace.contrib.aurora.client import AuroraClient

MODELS: Final[tuple[type[Model], ...]] = (Project, Registration)
"""List of models to synchronize."""


class SyncStep(BaseSyncStep):
    """Synchronization steps for aurora-related models."""

    PROJECTS = (auto(), lambda self: self.sync_projects)
    REGISTRATIONS = (auto(), lambda self: self.sync_registrations)


@dataclass
class SyncContextAurora(BaseSync):
    """Context for synchronizing Aurora-related models."""

    SyncStep = SyncStep
    client: AuroraClient = field(default_factory=AuroraClient)

    def sync_projects(self) -> None:
        """Fetch and process Project records from the Aurora system."""
        self.sync_entity(
            SyncConfig(
                model=Project,
                reference_id="reference_pk",
                endpoint=EndpointConfig(
                    path="project",
                    params={"modified_after": self.get_updated_at_after(Project)},
                ),
                prepare_defaults=lambda r: {"name": r["name"]},
            ),
        )

    def sync_registrations(self) -> None:
        """Fetch and process Registration records from the Aurora system."""

        def _prepare_defaults(rec: dict[str, Any]) -> dict[str, Any] | None:
            if (extracted_id := self._extract_related_id(rec["project"])) is None:
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

        self.sync_projects()
        self.sync_entity(
            SyncConfig(
                model=Registration,
                reference_id="reference_pk",
                endpoint=EndpointConfig(
                    path="registration",
                    params={"modified_after": self.get_updated_at_after(Registration)},
                ),
                prepare_defaults=_prepare_defaults,
            ),
        )

    def _extract_related_id(self, url: str) -> int | None:
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


def sync_context_aurora(
    step: SyncStep | None = None,
    stdout: TextIOBase | None = None,
) -> dict[str, Any]:
    """Run synchronization for geo-related models.

    Args:
        step (SyncStep | None): Specific step to execute (e.g., SyncStep.REGISTRATIONS). If None, all steps are run.
        stdout (TextIOBase | None): Optional output stream for logging.

    Returns:
        dict[str, Any]: Synchronization results, including counts and errors.

    """
    return sync_context(
        SyncContextAurora,
        step=step,
        stdout=stdout,
    )
