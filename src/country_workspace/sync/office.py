from typing import Optional

from django.utils import timezone

from hope_flex_fields.models import DataChecker

from country_workspace.models import Office, Program, SyncLog

from .. import constants
from .client import HopeClient


def sync_offices() -> int:
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


def sync_programs(limit_to_office: "Optional[Office]" = None) -> int:
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


def sync_lookup(sl: SyncLog):
    fd = sl.content_object
    if not fd:
        return
    client = HopeClient()
    record = client.get_lookup(sl.data["remote_url"])
    choices = []
    for k, v in record.items():
        choices.append((k, v))
    if not fd.attrs:
        fd.attrs = {}
    fd.attrs["choices"] = choices
    fd.save()
    sl.last_update_date = timezone.now()
    sl.save()


def sync_lookups() -> bool:
    for sl in SyncLog.objects.filter(object_id__gt=0).exclude(content_type__isnull=True):
        sync_lookup(sl)
    return True


def sync_all() -> bool:
    sync_offices()
    sync_programs()
    sync_lookups()
    return True
