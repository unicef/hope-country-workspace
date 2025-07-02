from io import TextIOBase
from typing import Any, Final
from dataclasses import dataclass, field
from enum import auto
from django.db.models import Model

from hope_flex_fields.models import DataChecker

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.contrib.hope.sync.base import (
    BaseSync,
    SyncConfig,
    SkipRecordError,
    EndpointConfig,
    BaseSyncStep,
    ParamDateName,
    sync_context,
)
from country_workspace.models import BeneficiaryGroup, Office, Program


MODELS: Final[tuple[type[Model], ...]] = (Office, Program, BeneficiaryGroup)
"""List of models to synchronize."""


class SyncStep(BaseSyncStep):
    """Synchronization steps for program-related models."""

    OFFICES = (auto(), lambda self: self.sync_offices)
    PROGRAMS = (auto(), lambda self: self.sync_programs)


@dataclass
class SyncContextPrograms(BaseSync):
    """Context for synchronizing program-related models."""

    SyncStep = SyncStep
    programs_limit_to_office: Office | None = None
    default_checkers: dict[str, DataChecker] = field(
        default_factory=lambda: {
            name: DataChecker.objects.filter(name=const_name).first()
            for name, const_name in (
                ("hh", HOUSEHOLD_CHECKER_NAME),
                ("ind", INDIVIDUAL_CHECKER_NAME),
                ("ppl", PEOPLE_CHECKER_NAME),
            )
        }
    )

    def sync_offices(self) -> None:
        """Fetch and process Office records from the remote API, deactivating those not present in the source."""
        self.sync_entity(
            SyncConfig(
                model=Office,
                reference_id="hope_id",
                endpoint=self._build_endpoint("business_areas", Office, ParamDateName.UPDATED),
                prepare_defaults=lambda r: {f: r.get(f) for f in ("name", "slug", "code", "long_name", "active")},
                should_process=lambda r: r.get("active"),
            ),
        )
        self.sync_programs()

    def sync_beneficiary_groups(self) -> None:
        """Fetch and process BeneficiaryGroup records from the remote API."""
        self.sync_entity(
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
            )
        )

    def sync_programs(self) -> None:
        """Synchronize and process Program records from the remote API, applying filters and post-processing.

        Notes:
            Calls sync_beneficiary_groups to ensure dependencies are synchronized.

        """

        def _should_process(record: dict[str, Any]) -> bool:
            return record.get("status") in [Program.ACTIVE, Program.DRAFT] and (
                not self.programs_limit_to_office or record["business_area_code"] == self.programs_limit_to_office.code
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
            if created and self.default_checkers:
                program.household_checker = self.default_checkers.get("hh")
                program.individual_checker = (
                    self.default_checkers.get("ind")
                    if program.beneficiary_group.master_detail
                    else self.default_checkers.get("ppl")
                )
                if program.household_checker or program.individual_checker:
                    program.save(update_fields=("household_checker", "individual_checker"))

        self.sync_beneficiary_groups()
        self.sync_entity(
            SyncConfig(
                model=Program,
                reference_id="hope_id",
                endpoint=self._build_endpoint("programs", Program, ParamDateName.UPDATED),
                prepare_defaults=_prepare_defaults,
                should_process=_should_process,
                post_process=_post_process,
            ),
        )


def sync_context_programs(
    *,
    delta_sync: bool,
    step: SyncStep | None = None,
    stdout: TextIOBase | None = None,
    programs_limit_to_office: Office | None = None,
) -> dict[str, Any]:
    """Run synchronization for program-related models.

    Args:
        delta_sync (bool): If True, only synchronize records updated after the last sync,
            otherwise synchronize all records.
        step (SyncStep | None): Specific step to execute (e.g., SyncStep.OFFICES). If None, all steps are run.
        stdout (TextIOBase | None): Optional output stream for logging.
        programs_limit_to_office (Office | None): Optional Office to limit program synchronization.

    Returns:
        dict[str, Any]: Synchronization results, including counts and errors.

    """
    return sync_context(
        SyncContextPrograms,
        delta_sync=delta_sync,
        step=step,
        stdout=stdout,
        programs_limit_to_office=programs_limit_to_office,
    )
