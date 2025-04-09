from io import TextIOBase
from typing import Any, Final
from dataclasses import dataclass
from enum import auto
from django.db.models import Model
from mptt.exceptions import InvalidMove

from ....models import Country, AreaType, Area
from .base import BaseSync, SyncConfig, BaseSyncStep, sync_context, SkipRecordError, LogLevel, EndpointConfig


MODELS: Final[tuple[type[Model], ...]] = (Country,)
"""List of models to synchronize."""


class SyncStep(BaseSyncStep):
    """Synchronization steps for geo-related models."""

    COUNTRIES = (auto(), lambda self: self.sync_countries)
    AREATYPES = (auto(), lambda self: self.sync_area_types)
    AREAS = (auto(), lambda self: self.sync_areas)


@dataclass
class SyncContextGeo(BaseSync):
    """Context for synchronizing geo-related models."""

    SyncStep = SyncStep

    def sync_countries(self) -> None:
        """Fetch and process Country records from the remote API."""
        self.sync_entity(
            SyncConfig(
                model=Country,
                endpoint=EndpointConfig(path="lookups/country"),
                prepare_defaults=lambda r: {f: r.get(f) for f in ("name", "iso_code2", "iso_code3")},
            ),
        )

    def sync_area_types(self) -> None:
        """Fetch and process AreaType records from the remote API.

        Notes:
            Calls sync_countries first to ensure dependencies are synchronized.

        """

        def _prepare_defaults(rec: dict[str, Any]) -> dict[str, Any] | None:
            try:
                country = Country.objects.get(hope_id=rec["country"])
            except Country.DoesNotExist as e:
                raise SkipRecordError("Country not found.") from e
            if parent_id := rec.get("parent"):
                parent_mapping[rec["id"]] = parent_id
            return {
                "name": rec["name"],
                "country": country,
                "area_level": rec.get("area_level", 1),
                "valid_from": rec.get("valid_from"),
                "valid_until": rec.get("valid_until"),
                "extras": rec.get("extras", {}),
            }

        parent_mapping = {}
        self.sync_countries()
        self.sync_entity(
            SyncConfig(
                model=AreaType,
                endpoint=EndpointConfig(
                    path="areatypes",
                    params={"updated_at_after": self.get_updated_at_after(AreaType)},
                ),
                prepare_defaults=_prepare_defaults,
            ),
        )
        self._assign_parents(AreaType, parent_mapping)
        AreaType.objects.rebuild()

    def sync_areas(self) -> None:
        """Fetch and process Area records from the remote API.

        Notes:
            Calls sync_area_types first to ensure dependencies are synchronized.

        """

        def _prepare_defaults(rec: dict[str, Any]) -> dict[str, Any] | None:
            try:
                area_type = AreaType.objects.get(hope_id=rec["area_type"])
            except AreaType.DoesNotExist as e:
                raise SkipRecordError("AreaType not found.") from e
            if parent_id := rec.get("parent"):
                parent_mapping[rec["id"]] = parent_id
            return {
                "name": rec["name"],
                "area_type": area_type,
                "p_code": rec.get("p_code"),
                "valid_from": rec.get("valid_from"),
                "valid_until": rec.get("valid_until"),
                "extras": rec.get("extras", {}),
            }

        parent_mapping = {}
        self.sync_area_types()
        self.sync_entity(
            SyncConfig(
                model=Area,
                endpoint=EndpointConfig(
                    path="areas",
                    params={"updated_at_after": self.get_updated_at_after(Area)},
                ),
                prepare_defaults=_prepare_defaults,
            ),
        )
        self._assign_parents(Area, parent_mapping)
        Area.objects.rebuild()

    def _assign_parents(self, model: type[Model], parent_mapping: dict[str, str]) -> None:
        """Assign parent relationships for the given model based on the parent mapping."""
        updates = []
        for child_id, parent_id in parent_mapping.items():
            try:
                instance = model.objects.get(hope_id=child_id)
            except model.DoesNotExist:
                self.emit_log(
                    "RECORD_SKIPPED",
                    hope_id=child_id,
                    error=f"{model._meta.model_name}: child '{child_id}' not found for parent assignment",
                )
                continue
            try:
                parent = model.objects.get(hope_id=parent_id)
            except model.DoesNotExist:
                self.emit_log(
                    "RECORD_SKIPPED",
                    hope_id=child_id,
                    error=f"{model._meta.model_name} parent '{parent_id}' not found for assignment",
                )
                continue
            instance.parent = parent
            updates.append(instance)

        if updates:
            try:
                model.objects.bulk_update(updates, fields=["parent"])
            except InvalidMove as e:
                self.emit_log(
                    "RECORD_SYNC_FAILURE",
                    LogLevel.ERROR,
                    hope_id="multiple",
                    error=f"Invalid MPTT move during bulk update for '{model._meta.model_name}': {e}",
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
