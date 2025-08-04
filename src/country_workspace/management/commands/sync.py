import logging
from argparse import ArgumentParser
from typing import Any
from django.core.management import BaseCommand

from country_workspace.contrib.hope.sync.base import log_to
from country_workspace.contrib.hope.sync.context_programs import sync_beneficiary_groups, sync_offices, sync_programs
from country_workspace.contrib.hope.sync.context_geo import sync_area_types, sync_countries, sync_areas

logger = logging.getLogger(__name__)


ONLY_CONTEXT_PROGRAMS = "only_context_programs"
ONLY_CONTEXT_GEO = "only_context_geo"


def run_program_sync() -> None:
    sync_offices()
    sync_beneficiary_groups()
    sync_programs()


def run_geo_sync() -> None:
    sync_countries()
    sync_area_types()
    sync_areas()


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

    def handle(self, *args: Any, **options: Any) -> None:
        with log_to(self.stdout):
            sync_functions = []
            if options.get(ONLY_CONTEXT_PROGRAMS) or options.get(ONLY_CONTEXT_GEO):
                if options.get(ONLY_CONTEXT_PROGRAMS):
                    sync_functions.append(run_program_sync)
                if options.get(ONLY_CONTEXT_GEO):
                    sync_functions.append(run_geo_sync)
            else:
                sync_functions.extend((run_program_sync, run_geo_sync))

            for sync_function in sync_functions:
                sync_function()
