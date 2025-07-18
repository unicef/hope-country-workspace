import logging
from argparse import ArgumentParser
from typing import Any
from django.core.management import BaseCommand

from country_workspace.contrib.hope.sync.context_programs import sync_context_programs
from country_workspace.contrib.hope.sync.context_geo import sync_context_geo


logger = logging.getLogger(__name__)


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
            dest="only_context_programs",
            default=False,
            help="Only sync context programs",
        )
        parser.add_argument(
            "--only-context-geo",
            action="store_true",
            dest="only_context_geo",
            default=False,
            help="Only sync context geo",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options.get("only_context_programs"):
            funcs = (sync_context_programs,)
        elif options.get("only_context_geo"):
            funcs = (sync_context_geo,)
        else:
            funcs = (sync_context_programs, sync_context_geo)
        [f(delta_sync=False, stdout=options.get("stdout")) for f in funcs]
