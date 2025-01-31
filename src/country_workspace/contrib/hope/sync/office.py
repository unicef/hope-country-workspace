from io import TextIOBase

from django.core.cache import cache

from hope_flex_fields.models import DataChecker

from .. import constants
from ..client import HopeClient
from country_workspace.models import Office, Program, SyncLog, Registration


def sync_offices(stdout: TextIOBase | None = None) -> dict[str, int]:
    client = HopeClient()
    totals = {"add": 0, "upd": 0}
    if stdout:
        stdout.write("Fetching office data from HOPE...")
    with cache.lock("sync-offices"):
        for record in client.get("business_areas"):
            if record["active"]:
                __, created = Office.objects.get_or_create(
                    hope_id=record["id"],
                    defaults={
                        "name": record["name"],
                        "slug": record["slug"],
                        "code": record["code"],
                        "active": record["active"],
                        "long_name": record["long_name"],
                    },
                )
                totals["add" if created else "upd"] += 1
        SyncLog.objects.register_sync(Office)
        return totals


def sync_programs(limit_to_office: "Office | None" = None, stdout: TextIOBase | None = None) -> dict[str, int]:
    if stdout:
        stdout.write("Fetching Programs data from HOPE...")
    client = HopeClient()
    hh_chk = DataChecker.objects.filter(name=constants.HOUSEHOLD_CHECKER_NAME).first()
    ind_chk = DataChecker.objects.filter(name=constants.INDIVIDUAL_CHECKER_NAME).first()
    totals = {"add": 0, "upd": 0, "skipped": 0}
    if limit_to_office:
        office = limit_to_office
    with cache.lock("sync-programs"):
        for record in client.get("programs"):
            try:
                if limit_to_office and record["business_area_code"] != office.code:
                    continue
                office = Office.objects.get(code=record["business_area_code"])
                if record["status"] not in [Program.ACTIVE, Program.DRAFT]:
                    continue
                p, created = Program.objects.get_or_create(
                    hope_id=record["id"],
                    defaults={
                        "name": record["name"],
                        "code": record["programme_code"],
                        "status": record["status"],
                        "sector": record["sector"],
                        "country_office": office,
                    },
                )
                if created:
                    totals["add"] += 1
                    p.household_checker = hh_chk
                    p.individual_checker = ind_chk
                    p.save()
                else:
                    totals["upd"] += 1
            except Office.DoesNotExist:
                totals["skipped"] += 1
        SyncLog.objects.register_sync(Program)
    return totals


def sync_registrations(stdout: TextIOBase | None = None) -> dict[str, int]:
    if stdout:
        stdout.write("Fetching Registrations data from HOPE...")
    client = HopeClient()
    totals = {"add": 0, "upd": 0, "skipped": 0}
    with cache.lock("sync-registrations"):
        for record in client.get("systems/aurora/registrations"):
            try:
                program = Program.objects.get(pk=record["project"])
            except Program.DoesNotExist:
                totals["skipped"] += 1
                continue
            __, created = Registration.objects.get_or_create(
                country_office=program.country_office,
                program=program,
                name=record["name"],
                reference_pk=record["aurora_id"],
            )
            totals["add" if created else "upd"] += 1
        SyncLog.objects.register_sync(Registration)
    return totals


def sync_all(stdout: TextIOBase | None = None) -> bool:
    sync_offices(stdout=stdout)
    sync_programs(stdout=stdout)
    sync_registrations(stdout=stdout)
    SyncLog.objects.refresh()
    return True
