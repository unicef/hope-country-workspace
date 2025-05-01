from io import TextIOBase
from typing import Any, Final
from dataclasses import dataclass
from enum import auto
from django.db.models import Model

from ....models import Country
from .base import BaseSync, SyncConfig, BaseSyncStep, sync_context


MODELS: Final[tuple[type[Model], ...]] = (Country,)
"""List of models to synchronize."""


class SyncStep(BaseSyncStep):
    """Synchronization steps for geo-related models."""

    COUNTRIES = (auto(), lambda self: self.sync_countries)


@dataclass
class SyncContextGeo(BaseSync):
    """Context for synchronizing geo-related models."""

    SyncStep = SyncStep

    def sync_countries(self) -> None:
        """Fetch and process Country records from the remote API."""
        self.sync_entity(
            SyncConfig(
                model=Country,
                path="lookups/country",
                prepare_defaults=lambda r: {f: r.get(f) for f in ("name", "iso_code2", "iso_code3")},
            ),
        )


def sync_context_geo(
    step: SyncStep | None = None,
    stdout: TextIOBase | None = None,
) -> dict[str, Any]:
    """Run synchronization for geo-related models.

    Args:
        step (SyncStep | None): Specific step to execute (e.g., SyncStep.COUNTRIES). If None, all steps are run.
        stdout (TextIOBase | None): Optional output stream for logging.

    Returns:
        dict[str, Any]: Synchronization results, including counts and errors.

    """
    return sync_context(
        SyncContextGeo,
        step=step,
        stdout=stdout,
    )
