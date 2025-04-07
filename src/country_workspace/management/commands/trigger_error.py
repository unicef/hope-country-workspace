import logging
from typing import Any

import sentry_sdk
from django.core.management import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            1 / 0  # noqa: B018
        except ValueError as e:  # pragma: no cover
            sentry_sdk.capture_exception(e)
