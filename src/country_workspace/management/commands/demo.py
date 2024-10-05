import logging
from random import randint
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import BaseCommand
from django.utils.text import slugify

from country_workspace.models import Household, Individual
from country_workspace.models.program import Program

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        from django.contrib.sites.models import Site

        from flags.models import FlagState

        from country_workspace.models import CountryOffice, User

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

        CountryOffice.objects.get_or_create(
            slug=slugify(
                settings.TENANT_HQ,
            ),
            name=settings.TENANT_HQ,
        )

        analysts, __ = Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
        user, __ = User.objects.get_or_create(username="user")

        from faker import Faker

        faker = Faker()
        for co in ["afghanistan", "ukraine", "sudan", "haiti"]:
            co, __ = CountryOffice.objects.get_or_create(
                slug=co, code=co, name=co.capitalize()
            )
            for p in [1, 2, 3]:
                p, __ = Program.objects.get_or_create(
                    name=f"Program {p} ({co.slug})", country_office=co
                )
                for hx in range(50):
                    h, __ = Household.objects.get_or_create(
                        country_office=co, program=p, name=faker.name(), flex_fields={}
                    )
                    for ix in range(1, randint(2, 6)):
                        i, __ = Individual.objects.get_or_create(
                            country_office=co,
                            household=h,
                            program=p,
                            full_name=faker.name(),
                            flex_fields={},
                        )
