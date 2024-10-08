import logging
from typing import Any

from django.core.management import BaseCommand

from country_workspace.sync.office import sync_all

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:

        sync_all()
