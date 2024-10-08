from country_workspace.models import Office, Program, Relationship, SyncLog

from ..models.lookups import MaritalStatus, ObservedDisability, ResidenceStatus
from .client import HopeClient


def sync_offices():
    client = HopeClient()
    for i, record in enumerate(client.get("business_areas")):
        Office.objects.get_or_create(
            hope_id=record["id"],
            defaults={
                "name": record["name"],
                "slug": record["slug"],
                "code": record["code"],
                "active": record["active"],
                "long_name": record["long_name"],
            },
        )
    SyncLog.objects.register_sync(Office)
    return i


def sync_programs():
    client = HopeClient()
    for i, record in enumerate(client.get("programs")):
        Program.objects.get_or_create(
            hope_id=record["id"],
            defaults={
                "name": record["name"],
                "programme_code": record["programme_code"],
                "status": record["status"],
                "sector": record["sector"],
                "country_office": Office.objects.get(code=record["business_area_code"]),
            },
        )
    SyncLog.objects.register_sync(Program)
    return i


def sync_maritalstatus():
    client = HopeClient()
    record = client.get_lookup("lookups/maritalstatus")
    for k, v in record.items():
        MaritalStatus.objects.get_or_create(code=k, defaults={"label": v})
    SyncLog.objects.register_sync(MaritalStatus)
    return True


def sync_observeddisability():
    client = HopeClient()
    record = client.get_lookup("lookups/observeddisability")
    for k, v in record.items():
        ObservedDisability.objects.get_or_create(code=k, defaults={"label": v})
    SyncLog.objects.register_sync(ObservedDisability)
    return True


def sync_relationship():
    client = HopeClient()
    record = client.get_lookup("lookups/relationship")
    for k, v in record.items():
        Relationship.objects.get_or_create(code=k, defaults={"label": v})
    SyncLog.objects.register_sync(Relationship)
    return True


def sync_residencestatus():
    client = HopeClient()
    record = client.get_lookup("lookups/residencestatus")
    for k, v in record.items():
        ResidenceStatus.objects.get_or_create(code=k, defaults={"label": v})
    SyncLog.objects.register_sync(ResidenceStatus)
    return True


def sync_areas():
    pass


def sync_all():
    sync_offices()
    sync_programs()
    sync_maritalstatus()
    sync_observeddisability()
    sync_relationship()
    sync_residencestatus()
    return True
