from typing import Optional

from hope_flex_fields.models import DataChecker

from country_workspace.models import Office, Program, Relationship, SyncLog

from .. import constants
from ..models.lookups import (
    LookupMixin,
    MaritalStatus,
    ObservedDisability,
    ResidenceStatus,
)
from .client import HopeClient


def sync_offices():
    client = HopeClient()
    for i, record in enumerate(client.get("business_areas")):
        if record["active"]:
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


def sync_programs(limit_to_office: "Optional[Office]" = None):
    client = HopeClient()
    hh_chk = DataChecker.objects.filter(name=constants.HOUSEHOLD_CHECKER_NAME).first()
    ind_chk = DataChecker.objects.filter(name=constants.INDIVIDUAL_CHECKER_NAME).first()
    if limit_to_office:
        office = limit_to_office
    for i, record in enumerate(client.get("programs")):
        try:
            if limit_to_office and record["business_area_code"] != office.code:
                continue
            else:
                office = Office.objects.get(code=record["business_area_code"])
            p, created = Program.objects.get_or_create(
                hope_id=record["id"],
                defaults={
                    "name": record["name"],
                    "programme_code": record["programme_code"],
                    "status": record["status"],
                    "sector": record["sector"],
                    "country_office": office,
                },
            )
            if created:
                p.household_checker = hh_chk
                p.individual_checker = ind_chk
                p.save()
        except Office.DoesNotExist:
            pass
    SyncLog.objects.register_sync(Program)
    return i


def _sync_lookup_model(model: type[LookupMixin], url: str):
    client = HopeClient()
    record = client.get_lookup(url)
    choices = []
    for k, v in record.items():
        model.objects.get_or_create(code=k, defaults={"label": v})
        choices.append((k, v))
    SyncLog.objects.register_sync(model)
    if fd := model.get_field_definition():
        fd.attrs["choices"] = choices
        fd.save()
    return len(choices)


def sync_maritalstatus():
    return _sync_lookup_model(MaritalStatus, "lookups/maritalstatus")


def sync_observeddisability():
    return _sync_lookup_model(ObservedDisability, "lookups/observeddisability")


def sync_relationship():
    return _sync_lookup_model(Relationship, "lookups/relationship")


def sync_residencestatus():
    return _sync_lookup_model(ResidenceStatus, "lookups/residencestatus")


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
