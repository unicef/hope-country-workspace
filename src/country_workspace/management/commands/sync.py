import logging
from argparse import ArgumentParser
from typing import Any
from django.core.management import BaseCommand

from country_workspace.contrib.hope.sync.base import Stats, log_to
from country_workspace.contrib.hope.sync.context_programs import sync_beneficiary_groups, sync_offices, sync_programs
from country_workspace.contrib.hope.sync.context_geo import sync_area_types, sync_countries, sync_areas
from country_workspace.models import SyncLog

logger = logging.getLogger(__name__)


ONLY_CONTEXT_PROGRAMS = "only_context_programs"
ONLY_CONTEXT_GEO = "only_context_geo"
ONLY_FLEX_FIELDS = "only_flex_fields"


def run_program_sync(delta_sync: bool = False) -> dict[str, Stats]:
    return {
        "offices": sync_offices(delta_sync=delta_sync),
        "beneficiary_groups": sync_beneficiary_groups(delta_sync=delta_sync),
        "programs": sync_programs(delta_sync=delta_sync),
    }


def run_geo_sync(delta_sync: bool = False) -> dict[str, Stats]:
    return {
        "countries": sync_countries(delta_sync=delta_sync),
        "area_types": sync_area_types(delta_sync=delta_sync),
        "areas": sync_areas(delta_sync=delta_sync),
    }


def run_flex_fields_sync() -> dict[str, int]:
    return {"refreshed": SyncLog.objects.refresh()}


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--no-input",
            action="store_true",
            dest="no_input",
            default=False,
            help="Do not ask confirmation",
        )
        parser.add_argument(
            "--only-context-programs",
            action="store_true",
            dest=ONLY_CONTEXT_PROGRAMS,
            default=False,
            help="Only sync context programs",
        )
        parser.add_argument(
            "--only-context-geo",
            action="store_true",
            dest=ONLY_CONTEXT_GEO,
            default=False,
            help="Only sync context geo",
        )
        parser.add_argument(
            "--only-flex-fields",
            action="store_true",
            dest=ONLY_FLEX_FIELDS,
            default=False,
            help="Only refresh HOPE flex field lookups",
        )
        parser.add_argument(
            "--delta",
            action="store_true",
            dest="delta_sync",
            default=False,
            help="Use delta sync (fetch only records updated since the last sync) for programs and geo data",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        delta_sync: bool = options.get("delta_sync", False)
        with log_to(self.stdout):
            selectors = (
                options.get(ONLY_CONTEXT_PROGRAMS),
                options.get(ONLY_CONTEXT_GEO),
                options.get(ONLY_FLEX_FIELDS),
            )
            run_all = not any(selectors)
            sync_functions: list[Any] = []
            if run_all or options.get(ONLY_CONTEXT_PROGRAMS):
                sync_functions.append(lambda: run_program_sync(delta_sync=delta_sync))
            if run_all or options.get(ONLY_CONTEXT_GEO):
                sync_functions.append(lambda: run_geo_sync(delta_sync=delta_sync))
            if run_all or options.get(ONLY_FLEX_FIELDS):
                sync_functions.append(run_flex_fields_sync)
            for sync_function in sync_functions:
                sync_function()
