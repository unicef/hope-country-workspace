import logging
from typing import Any, Final

from django.db.models import Model
from mptt.exceptions import InvalidMove

from country_workspace.admin.sync import Stats
from country_workspace.contrib.hope.sync.base import (
    SyncConfig,
    SkipRecordError,
    ParamDateName,
    sync_entity,
    build_endpoint,
    format_msg,
)
from country_workspace.models import Country, AreaType, Area

MODELS: Final[tuple[type[Model], ...]] = (Country,)
"""List of models to synchronize."""


def sync_countries(delta_sync: bool = False) -> Stats:
    return sync_entity(
        SyncConfig(
            model=Country,
            reference_id="hope_id",
            endpoint=build_endpoint("lookups/country", Country, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=lambda r: {f: r.get(f) for f in ("name", "iso_code2", "iso_code3")},
            delta_sync=delta_sync,
        )
    )


def sync_area_types(delta_sync: bool = False) -> Stats:
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
    result = sync_entity(
        SyncConfig(
            model=AreaType,
            reference_id="hope_id",
            endpoint=build_endpoint("areatypes", AreaType, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=_prepare_defaults,
            delta_sync=delta_sync,
        )
    )
    _assign_parents(AreaType, parent_mapping)
    AreaType.objects.rebuild()

    return result


def sync_areas(delta_sync: bool = False) -> Stats:
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
    result = sync_entity(
        SyncConfig(
            model=Area,
            reference_id="hope_id",
            endpoint=build_endpoint("areas", Area, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=_prepare_defaults,
            delta_sync=delta_sync,
        )
    )
    _assign_parents(Area, parent_mapping)
    Area.objects.rebuild()

    return result


def _assign_parents(model: type[Model], parent_mapping: dict[str, str]) -> None:
    """Bulk-assign parents from mapping."""
    updates = []
    for child_id, parent_id in parent_mapping.items():
        try:
            instance = model.objects.get(hope_id=child_id)
        except model.DoesNotExist:
            logging.info(
                format_msg(
                    "RECORD_SKIPPED",
                    reference_id_val=child_id,
                    error=f"{model._meta.model_name}: child '{child_id}' not found for parent assignment",
                )
            )
            continue
        try:
            parent = model.objects.get(hope_id=parent_id)
        except model.DoesNotExist:
            logging.info(
                format_msg(
                    "RECORD_SKIPPED",
                    reference_id_val=child_id,
                    error=f"{model._meta.model_name} parent '{parent_id}' not found for assignment",
                )
            )
            continue
        instance.parent = parent
        updates.append(instance)

    if updates:
        try:
            model.objects.bulk_update(updates, fields=["parent"])
        except InvalidMove as e:
            logging.error(
                format_msg(
                    "RECORD_SYNC_FAILURE",
                    reference_id_val="multiple",
                    error=f"Invalid MPTT move during bulk update for '{model._meta.model_name}': {e}",
                )
            )
