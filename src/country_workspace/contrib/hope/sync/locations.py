from collections.abc import Generator
from typing import Any
from dataclasses import dataclass, field

from django.core.cache import cache
from django.db import DatabaseError, models, transaction

from ....models import AsyncJob, SyncLog, Country, AreaType, Area
from ....exceptions import RemoteError
from ..client import HopeClient


class PrefetchError(Exception): ...


@dataclass
class SyncLocations:
    """Handles synchronization of locations data from the HOPE core."""

    client: HopeClient = field(default_factory=HopeClient)
    total: dict[str, dict[str, int] | list[str]] = field(
        default_factory=lambda: {**{_: {"add": 0, "upd": 0} for _ in ("country", "areatype", "area")}, "errors": []}
    )

    def _get_pk_map(self, model_cls: type[models.Model]) -> dict[str, int]:
        try:
            return {_["hope_id"]: _["pk"] for _ in model_cls.objects.values("pk", "hope_id")}
        except DatabaseError as e:
            msg = f"Failed to pre-fetch PK map for '{model_cls._meta.model_name}': {e}"
            self.total["errors"].append(msg)
            raise PrefetchError(msg) from e

    def _get_object_map(self, model_cls: type[models.Model]) -> dict[Any, models.Model]:
        try:
            return {obj.hope_id: obj for obj in model_cls.objects.all()}
        except DatabaseError as e:
            msg = f"Failed to pre-fetch object map for '{model_cls._meta.model_name}': {e}"
            self.total["errors"].append(msg)
            raise PrefetchError(msg) from e

    def sync_country(self) -> None:
        """Synchronize country data from the HOPE core."""
        try:
            with transaction.atomic():
                for record in self.safe_get("lookups/country"):
                    if not (hope_id := record.get("id")):
                        self.total["errors"].append("Missing 'hope_id' in country record")
                        continue
                    __, created = Country.objects.update_or_create(
                        hope_id=hope_id,
                        defaults={"name": record["name"], "iso_code2": record["iso_code2"]},
                    )
                    self.total["country"]["add" if created else "upd"] += 1
                SyncLog.objects.register_sync(Country)
        except DatabaseError as e:
            self.total["errors"].append(f"Fatal database error during sync (Country), transaction rolled back: {e}")

    def sync_areatype(self) -> None:
        """Synchronize area type data from the HOPE core."""
        try:
            country_map = self._get_object_map(Country)
            areatype_pk_map = self._get_pk_map(AreaType)
            with transaction.atomic():
                for record in self.safe_get("areatypes"):
                    if not (hope_id := record.get("id")):
                        self.total["errors"].append("Missing 'hope_id' in area type record")
                        continue
                    country = country_map.get(record["country"])
                    if not country:
                        self.total["errors"].append(f"Country not found for area type record with hope_id: {hope_id}")
                        continue
                    at, created = AreaType.objects.update_or_create(
                        hope_id=hope_id,
                        defaults={
                            "name": record["name"],
                            "country": country,
                            "area_level": record["area_level"],
                            "parent_id": areatype_pk_map.get(record.get("parent")),
                            "valid_from": record["valid_from"],
                            "valid_until": record["valid_until"],
                            "extras": record["extras"],
                        },
                    )
                    self.total["areatype"]["add" if created else "upd"] += 1
                    if created:
                        areatype_pk_map[hope_id] = at.pk
                SyncLog.objects.register_sync(AreaType)
        except PrefetchError:
            return
        except DatabaseError as e:
            self.total["errors"].append(f"Fatal database error during sync (Area Type), transaction rolled back: {e}")

    def sync_area(self) -> None:
        """Synchronize area data from the HOPE core."""
        areatype_map = self._get_object_map(AreaType)
        area_pk_map = self._get_pk_map(Area)
        try:
            with transaction.atomic():
                for record in self.safe_get("areas"):
                    if not (hope_id := record.get("id")):
                        self.total["errors"].append("Missing 'hope_id' in area record")
                        continue
                    area_type = areatype_map.get(record["area_type"])
                    if not area_type:
                        self.total["errors"].append(f"Area type not found for area record with hope_id: {hope_id}")
                        continue
                    a, created = Area.objects.update_or_create(
                        hope_id=hope_id,
                        defaults={
                            "name": record["name"],
                            "parent_id": area_pk_map.get(record.get("parent")),
                            "p_code": record["p_code"],
                            "area_type": area_type,
                            "valid_from": record["valid_from"],
                            "valid_until": record["valid_until"],
                            "extras": record["extras"],
                        },
                    )
                    self.total["area"]["add" if created else "upd"] += 1
                    if created:
                        area_pk_map[hope_id] = a.pk
                SyncLog.objects.register_sync(Area)
        except PrefetchError:
            return
        except DatabaseError as e:
            self.total["errors"].append(f"Fatal database error during sync (Area), transaction rolled back: {e}")

    def safe_get(self, path: str) -> Generator[dict[str, Any], None, None] | None:
        try:
            yield from self.client.get(path)
        except RemoteError as e:
            self.total["errors"].append(f"API Error fetching {path}: {e}")
            return None


def sync_all(job: AsyncJob) -> dict[str, Any]:
    with cache.lock("sync-locations"):
        sync = SyncLocations()
        for step in (sync.sync_country, sync.sync_areatype, sync.sync_area):
            step()
            if sync.total["errors"]:
                return sync.total
        return sync.total
