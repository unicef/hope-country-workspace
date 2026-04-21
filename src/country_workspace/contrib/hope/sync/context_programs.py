from collections.abc import Callable
from typing import Any, Final, Mapping, Literal

from constance import config as constance_config
from django.db.models import Model
from hope_flex_fields.models import DataChecker

from country_workspace.admin.sync import Stats
from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.contrib.hope.sync.base import (
    SyncConfig,
    SkipRecordError,
    ParamDateName,
    sync_entity,
    build_endpoint,
)
from country_workspace.models import BeneficiaryGroup, Country, Office, Program

MODELS: Final[tuple[type[Model], ...]] = (Office, Program, BeneficiaryGroup)
"""List of models to synchronize."""

OFFICE_FIELDS = "name", "slug", "code", "long_name", "active"
BENEFICIARY_GROUP_FIELDS = (
    "name",
    "group_label",
    "group_label_plural",
    "member_label",
    "member_label_plural",
    "master_detail",
)

HOPE_ID = "hope_id"
BUSINESS_AREAS = "business-areas"
BENEFICIARY_GROUPS = "beneficiary-groups"
PROGRAMS = "programs"


def get_default_checkers() -> Mapping[str, DataChecker | None]:
    target_to_checker_name = {"hh": HOUSEHOLD_CHECKER_NAME, "ind": INDIVIDUAL_CHECKER_NAME, "ppl": PEOPLE_CHECKER_NAME}
    checker_by_name = {c.name: c for c in DataChecker.objects.filter(name__in=target_to_checker_name.values())}
    return {k: checker_by_name.get(v) for k, v in target_to_checker_name.items()}


def get_field_extractor(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def field_extractor(record: dict[str, Any]) -> dict[str, Any]:
        return {field: record.get(field) for field in fields}

    return field_extractor


def should_process_office(record: dict[str, Any]) -> bool:
    return bool(record.get("active"))


def make_office_countries_m2m_hook() -> Callable[[Office, dict[str, Any]], None]:
    by_iso2 = {iso2.upper(): pk for iso2, pk in Country.objects.values_list("iso_code2", "pk")}

    def m2m_hook(office: Office, record: dict[str, Any]) -> None:
        if "countries" not in record:
            return

        if not (raw := record.get("countries") or []):
            office.countries.clear()
            return

        pks = {by_iso2.get((item.get("iso_code2") or "").upper()) for item in raw if isinstance(item, dict)}
        office.countries.set(pk for pk in pks if pk)

    return m2m_hook


def sync_offices(delta_sync: bool = False) -> Stats:
    return sync_entity(
        SyncConfig[Office](
            model=Office,
            reference_id=HOPE_ID,
            endpoint=build_endpoint(BUSINESS_AREAS, Office, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=get_field_extractor(OFFICE_FIELDS),
            should_process=should_process_office,
            m2m_hook=make_office_countries_m2m_hook(),
            delta_sync=delta_sync,
        )
    )


def sync_beneficiary_groups(delta_sync: bool = False) -> Stats:
    return sync_entity(
        SyncConfig[BeneficiaryGroup](
            model=BeneficiaryGroup,
            reference_id=HOPE_ID,
            endpoint=build_endpoint(BENEFICIARY_GROUPS, BeneficiaryGroup, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=get_field_extractor(BENEFICIARY_GROUP_FIELDS),
            delta_sync=delta_sync,
        )
    )


def get_should_process_program(programs_limit_to_office: Office | None) -> Callable[[dict[str, Any]], bool]:
    def should_process_program(record: dict[str, Any]) -> bool:
        return record.get("status") in [Program.ACTIVE, Program.DRAFT] and (
            not programs_limit_to_office or record["business_area_code"] == programs_limit_to_office.code
        )

    return should_process_program


def prepare_program_defaults(record: dict[str, Any]) -> dict[str, Any] | None:
    try:
        office = Office.objects.get(code=record["business_area_code"])
    except Office.DoesNotExist as e:
        raise SkipRecordError("Office not found") from e

    try:
        bg = BeneficiaryGroup.objects.get(hope_id=record["beneficiary_group"])
    except BeneficiaryGroup.DoesNotExist as e:
        raise SkipRecordError("Beneficiary group not found") from e

    return {
        "beneficiary_group": bg,
        "biometric_deduplication_enabled": record["biometric_deduplication_enabled"],
        "code": record["code"],
        "country_office": office,
        "name": record["name"],
        "status": record["status"],
        "sector": record["sector"],
    }


def get_default_ignored_fields(entity_type: Literal["ind", "hh"]) -> str | None:
    """Collect ignored fields from all sources for given entity type (hh or ind).

    Args:
        entity_type: Either "hh" for household or "ind" for individual.

    Returns:
        Newline-separated string of field names, or None if no fields configured.

    """
    settings = [
        f"KOBO_{entity_type.upper()}_FIELDS_TO_IGNORE",
        f"AURORA_{entity_type.upper()}_FIELDS_TO_IGNORE",
        f"XLS_{entity_type.upper()}_FIELDS_TO_IGNORE",
    ]

    fields: set[str] = set()
    for setting in settings:
        value = getattr(constance_config, setting, "")
        if value:
            fields.update(f.strip() for f in value.split(",") if f.strip())

    return "\n".join(sorted(fields)) if fields else None


def post_process_program(program: Program, created: bool) -> None:
    if not created:
        return

    default_checkers = get_default_checkers()
    update_fields: list[str] = []

    program.household_checker = default_checkers.get("hh")
    program.individual_checker = (
        default_checkers.get("ind") if program.beneficiary_group.master_detail else default_checkers.get("ppl")
    )
    if program.household_checker or program.individual_checker:
        update_fields.extend(["household_checker", "individual_checker"])

    hh_ignored = get_default_ignored_fields("hh")
    if hh_ignored:
        program.hh_alien_columns_to_ignore = hh_ignored
        update_fields.append("hh_alien_columns_to_ignore")

    ind_ignored = get_default_ignored_fields("ind")
    if ind_ignored:
        program.ind_alien_columns_to_ignore = ind_ignored
        update_fields.append("ind_alien_columns_to_ignore")

    if update_fields:
        program.save(update_fields=update_fields)


def sync_programs(delta_sync: bool = False, programs_limit_to_office: Office | None = None) -> Stats:
    return sync_entity(
        SyncConfig[Program](
            model=Program,
            reference_id=HOPE_ID,
            endpoint=build_endpoint(PROGRAMS, Program, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=prepare_program_defaults,
            should_process=get_should_process_program(programs_limit_to_office),
            post_process=post_process_program,
            delta_sync=delta_sync,
        )
    )
