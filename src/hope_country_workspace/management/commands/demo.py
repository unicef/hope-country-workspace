from typing import Any

import logging

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

        from hope_country_workspace.security.models import CountryOffice, User

        Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={
                "domain": "localhost:8000",
                "name": "localhost",
            },
        )
        Site.objects.clear_cache()

        for flag in settings.FLAGS.keys():
            FlagState.objects.get_or_create(name=flag, condition="hostname", value="127.0.0.1,localhost")

        CountryOffice.objects.get_or_create(slug=slugify(settings.TENANT_HQ, ), name=settings.TENANT_HQ)

        for co in ["afghanistan", "ukraine", "sudan", "haiti"]:
            CountryOffice.objects.get_or_create(slug=co, name=co.capitalize())

        analysts, __ = Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
        afg, __ = CountryOffice.objects.get_or_create(slug="afghanistan")
        user, __ = User.objects.get_or_create(username="user")
        user.roles.get_or_create(group=analysts, country_office=afg)
