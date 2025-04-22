import logging
from argparse import ArgumentParser
from typing import Any

from django.core.management import BaseCommand

from country_workspace.contrib.hope.sync.context_programs import sync_context_programs

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

    def handle(self, *args: Any, **options: Any) -> None:
        sync_context_programs(stdout=self.stdout)
