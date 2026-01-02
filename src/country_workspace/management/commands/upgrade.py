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
            nargs="+",
            dest="superusers",
            default=None,
            help="Emails/usernames to grant superuser privileges (space-separated)",
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
        self.superusers = options["superusers"] if options["superusers"] is not None else env("SUPERUSERS", [])

    def halt(self, e: Exception) -> None:  # pragma: no cover
        self.stdout.write(str(e), style_func=self.style.ERROR)
        self.stdout.write("\n\n***", style_func=self.style.ERROR)
        self.stdout.write("SYSTEM HALTED", style_func=self.style.ERROR)
        self.stdout.write("Unable to start...", style_func=self.style.ERROR)
        if self.debug:
            raise e

        sys.exit(1)

    def _ensure_superuser(self, user: Any) -> bool:
        if user.is_staff and user.is_superuser:
            return False
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        return True

    def _run_createsuperuser(self, username: str, email: str) -> bool:
        os.environ["DJANGO_SUPERUSER_USERNAME"] = username
        os.environ["DJANGO_SUPERUSER_EMAIL"] = email

        if password := self.admin_password if username == self.admin_email else "":
            os.environ["DJANGO_SUPERUSER_PASSWORD"] = password
        else:
            os.environ.pop("DJANGO_SUPERUSER_PASSWORD", None)

        call_command(
            "createsuperuser",
            email=email,
            username=username,
            verbosity=max(self.verbosity - 1, 0),
            interactive=False,
        )
        return bool(password)

    def _superuser_logins(self) -> list[str]:
        raw = [self.admin_email, *self.superusers]
        return list(dict.fromkeys(s.strip() for s in raw if s))

    def _create_superusers(self, echo: Any) -> None:
        users = get_user_model().objects

        for login in self._superuser_logins():
            email = login if "@" in login else f"{login}@{FALLBACK_EMAIL_DOMAIN}"

            if user := (
                (users.filter(email=email).first() if "@" in login else None) or users.filter(username=login).first()
            ):
                changed = self._ensure_superuser(user)
                echo(
                    f"{'Granted superuser privileges' if changed else 'User found, skip'}: {login}",
                    style_func=self.style.WARNING,
                )
                continue

            validate_email(email)
            password_provided = self._run_createsuperuser(login, email)

            echo(
                f"Created superuser: {email}{'' if password_provided else ' with unusable password'}",
                style_func=self.style.WARNING,
            )

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

            self._create_superusers(echo)

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
