import logging
import sys
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import BaseCommand
from django.utils.text import slugify

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        from django.contrib.sites.models import Site

        from flags.models import FlagState

        from country_workspace.models import Office, User

        Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={
                "domain": "localhost:8000",
                "name": "localhost",
            },
        )
        Site.objects.clear_cache()

        for flag in settings.FLAGS.keys():
            FlagState.objects.get_or_create(
                name=flag, condition="hostname", value="127.0.0.1,localhost"
            )

        Office.objects.get_or_create(
            slug=slugify(
                settings.TENANT_HQ,
            ),
            name=settings.TENANT_HQ,
        )

        analysts, __ = Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
        user, __ = User.objects.get_or_create(username="user")

        test_utils_dir = (
            Path(__file__).parent.parent.parent.parent.parent / "tests/extras"
        )
        assert test_utils_dir.exists(), (  # nosec B101
            str(test_utils_dir.absolute()) + " does not exist"
        )
        sys.path.append(str(test_utils_dir.absolute()))
        import vcr
        from testutils.factories import HouseholdFactory
        from vcr.record_mode import RecordMode

        from country_workspace.sync.office import sync_all

        with vcr.use_cassette(
            test_utils_dir.parent / "sync_all.yaml",
            record_mode=RecordMode.NONE,
        ):
            sync_all()

        for co in Office.objects.filter(active=True):
            for p in co.programs.filter():
                HouseholdFactory.create_batch(10, country_office=co, program=p)
