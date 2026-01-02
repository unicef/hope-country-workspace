import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, call_command
from django.core.validators import validate_email
from django.utils.text import slugify

import country_workspace
from country_workspace.config import env
from country_workspace.security.utils import setup_workspace_group

if TYPE_CHECKING:
    from argparse import ArgumentParser

logger = logging.getLogger(__name__)


FALLBACK_EMAIL_DOMAIN: Final[str] = "example.org"


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def add_arguments(self, parser: "ArgumentParser") -> None:
        parser.add_argument(
            "--with-checks",
            action="store_true",
            dest="checks",
            default=False,
            help="Run checks",
        )
        parser.add_argument(
            "--no-migrate",
            action="store_false",
            dest="migrate",
            default=True,
            help="Do not run migrations",
        )
        parser.add_argument(
            "--prompt",
            action="store_true",
            dest="prompt",
            default=False,
            help="Let ask for confirmation",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            dest="debug",
            default=False,
            help="debug mode",
        )
        parser.add_argument(
            "--no-static",
            action="store_false",
            dest="static",
            default=True,
            help="Do not run collectstatic",
        )

        parser.add_argument(
            "--sync",
            action="store_true",
            dest="sync_with_hope",
            default=False,
            help="Run HOPE synchronisation",
        )

        parser.add_argument(
            "--admin-email",
            action="store",
            dest="admin_email",
            default="",
            help="Admin email",
        )
        parser.add_argument(
            "--admin-password",
            action="store",
            dest="admin_password",
            default="",
            help="Admin password",
        )
        parser.add_argument(
            "--superusers",
            action="store",
            dest="superusers",
            default="",
            help="Comma-separated list of emails/usernames to grant superuser privileges",
        )

    def get_options(self, options: dict[str, Any]) -> None:
        self.verbosity = options["verbosity"]
        self.run_check = options["checks"]
        self.prompt = not options["prompt"]
        self.static = options["static"]
        self.migrate = options["migrate"]
        self.debug = options["debug"]
        self.sync_with_hope = options["sync_with_hope"]

        self.admin_email = str(options["admin_email"] or env("ADMIN_EMAIL", ""))
        self.admin_password = str(options["admin_password"] or env("ADMIN_PASSWORD", ""))
        self.superusers = str(options["superusers"] or env("SUPERUSERS", ""))

    def halt(self, e: Exception) -> None:  # pragma: no cover
        self.stdout.write(str(e), style_func=self.style.ERROR)
        self.stdout.write("\n\n***", style_func=self.style.ERROR)
        self.stdout.write("SYSTEM HALTED", style_func=self.style.ERROR)
        self.stdout.write("Unable to start...", style_func=self.style.ERROR)
        if self.debug:
            raise e

        sys.exit(1)

    def superuser_identities(self) -> list[str]:
        items = (s.strip() for s in (self.admin_email, *self.superusers.split(",")))
        return list(dict.fromkeys(s for s in items if s))

    def create_superuser(self, *, email: str, username: str, password: str) -> None:
        os.environ["DJANGO_SUPERUSER_USERNAME"] = username
        os.environ["DJANGO_SUPERUSER_EMAIL"] = email
        os.environ["DJANGO_SUPERUSER_PASSWORD"] = password
        call_command(
            "createsuperuser",
            email=email,
            username=username,
            verbosity=self.verbosity - 1,
            interactive=False,
        )

    def ensure_superusers(self, echo: Any) -> None:
        # - Builds a **deduplicated, ordered** list of superuser identities from `ADMIN_EMAIL` (or `--admin-email`)
        #  plus `SUPERUSERS` (or `--superusers`, comma-separated).
        # - Each identity is treated as either an **email** (contains `@`) or a **username**; for usernames,
        #  a fallback email is derived as `"{username}@{FALLBACK_EMAIL_DOMAIN}"`.
        # - Lookup semantics are split:
        # - If identity is an **email**, it first searches by `email` (canonical), then by `username == identity`.
        # - If identity is a **username**, it searches **only by username** (email is not used for lookup).
        # - If a user exists, it ensures `is_staff=True` and `is_superuser=True` (updates only when needed).
        # - If the user does not exist, it validates the email and creates the account via Django `createsuperuser`;
        #  the password is `ADMIN_PASSWORD` if provided, otherwise the identity itself.

        users = get_user_model().objects
        for identity in self.superuser_identities():
            is_email = "@" in identity
            username = identity
            email = identity if is_email else f"{identity}@{FALLBACK_EMAIL_DOMAIN}"

            if user := (
                (users.filter(email=email).first() if is_email else None) or users.filter(username=username).first()
            ):
                if needs := not (user.is_staff and user.is_superuser):
                    user.is_staff = user.is_superuser = True
                    user.save(update_fields=["is_staff", "is_superuser"])
                echo(
                    f"{'Granted superuser privileges' if needs else 'User found, skip'}: {identity}",
                    style_func=self.style.WARNING,
                )
                continue

            validate_email(email)
            echo(f"Creating superuser: {email}", style_func=self.style.WARNING)
            self.create_superuser(email=email, username=username, password=self.admin_password or identity)

    def handle(self, *args: Any, **options: Any) -> None:
        from country_workspace.models import Office

        self.get_options(options)
        if self.verbosity >= 1:
            echo = self.stdout.write
        else:
            echo = lambda *a, **kw: None

        try:
            extra = {
                "no_input": not self.prompt,
                "verbosity": self.verbosity - 1,
                "stdout": self.stdout,
            }
            echo(f"Running upgrade of version {country_workspace.VERSION}", style_func=self.style.WARNING)

            if self.run_check:
                call_command("check", deploy=True, verbosity=self.verbosity - 1)
            if self.static:
                static_root = Path(env("STATIC_ROOT"))
                echo(f"Run collectstatic to: '{static_root}' - '{static_root.absolute()}")
                if not static_root.exists():
                    static_root.mkdir(parents=True)
                call_command("collectstatic", **extra)

            if self.migrate:
                echo("Run migrations")
                call_command("migrate", **extra)
                call_command("create_extra_permissions")

            echo("Remove stale contenttypes")
            call_command("remove_stale_contenttypes", **extra)
            if self.sync_with_hope:
                echo("Run HOPE synchronisation")
                call_command("sync", **extra)

            self.ensure_superusers(echo)

            echo("Setup base security")
            setup_workspace_group()
            Office.objects.get_or_create(
                slug=slugify(
                    settings.TENANT_HQ,
                ),
                name=settings.TENANT_HQ,
            )
            call_command("upgradescripts", ["apply"])
            echo("Upgrade completed", style_func=self.style.SUCCESS)
        except ValidationError as e:  # pragma: no cover
            self.halt(Exception("\n- ".join(["Wrong argument(s):", *e.messages])))
        except Exception as e:  # pragma: no cover
            self.stdout.write(str(e), style_func=self.style.ERROR)
            logger.exception(e)
            self.halt(e)
