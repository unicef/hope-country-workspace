from typing import Any, Final, Mapping

from django.db.models import Model
from hope_flex_fields.models import DataChecker

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.contrib.hope.sync.base import (
    SyncConfig,
    SkipRecordError,
    EndpointConfig,
    ParamDateName,
    sync_entity,
    build_endpoint,
)
from country_workspace.models import BeneficiaryGroup, Office, Program

MODELS: Final[tuple[type[Model], ...]] = (Office, Program, BeneficiaryGroup)
"""List of models to synchronize."""


def get_default_checkers() -> Mapping[str, DataChecker]:
    return {
        name: DataChecker.objects.filter(name=const_name).first()
        for name, const_name in (
            ("hh", HOUSEHOLD_CHECKER_NAME),
            ("ind", INDIVIDUAL_CHECKER_NAME),
            ("ppl", PEOPLE_CHECKER_NAME),
        )
    }


def sync_offices(delta_sync: bool = False) -> None:
    """Fetch and process Office records from the remote API, deactivating those not present in the source."""
    sync_entity(
        SyncConfig(
            model=Office,
            reference_id="hope_id",
            endpoint=build_endpoint("business_areas", Office, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=lambda r: {f: r.get(f) for f in ("name", "slug", "code", "long_name", "active")},
            should_process=lambda r: r.get("active"),
            delta_sync=delta_sync,
        )
    )


def sync_beneficiary_groups(delta_sync: bool = False) -> None:
    """Fetch and process BeneficiaryGroup records from the remote API."""
    sync_entity(
        SyncConfig(
            model=BeneficiaryGroup,
            reference_id="hope_id",
            endpoint=EndpointConfig(path="beneficiary-groups"),
            prepare_defaults=lambda r: {
                f: r.get(f)
                for f in (
                    "name",
                    "group_label",
                    "group_label_plural",
                    "member_label",
                    "member_label_plural",
                    "master_detail",
                )
            },
            delta_sync=delta_sync,
        )
    )


def sync_programs(delta_sync: bool = False, programs_limit_to_office: Office | None = None) -> None:
    """Synchronize and process Program records from the remote API, applying filters and post-processing.

    Notes:
        Calls sync_beneficiary_groups to ensure dependencies are synchronized.

    """

    def _should_process(record: dict[str, Any]) -> bool:
        return record.get("status") in [Program.ACTIVE, Program.DRAFT] and (
            not programs_limit_to_office or record["business_area_code"] == programs_limit_to_office.code
        )

    def _prepare_defaults(record: dict[str, Any]) -> dict[str, Any] | None:
        try:
            office = Office.objects.get(code=record["business_area_code"])
        except Office.DoesNotExist as e:
            raise SkipRecordError("Office not found") from e
        try:
            bg = BeneficiaryGroup.objects.get(hope_id=record["beneficiary_group"])
        except BeneficiaryGroup.DoesNotExist as e:
            raise SkipRecordError("Beneficiary group not found") from e
        return {
            "name": record["name"],
            "code": record["programme_code"],
            "status": record["status"],
            "sector": record["sector"],
            "country_office": office,
            "beneficiary_group": bg,
        }

    def _post_process(program: Program, created: bool) -> None:
        default_checkers = get_default_checkers()
        if created and default_checkers:
            program.household_checker = default_checkers.get("hh")
            program.individual_checker = (
                default_checkers.get("ind") if program.beneficiary_group.master_detail else default_checkers.get("ppl")
            )
            if program.household_checker or program.individual_checker:
                program.save(update_fields=("household_checker", "individual_checker"))

    sync_entity(
        SyncConfig(
            model=Program,
            reference_id="hope_id",
            endpoint=build_endpoint("programs", Program, ParamDateName.UPDATED, delta_sync),
            prepare_defaults=_prepare_defaults,
            should_process=_should_process,
            post_process=_post_process,
            delta_sync=delta_sync,
        )
    )
