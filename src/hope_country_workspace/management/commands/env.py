from typing import TYPE_CHECKING

from django.core.management import BaseCommand, CommandError, CommandParser

if TYPE_CHECKING:
    from typing import Any

DEVELOP = {
    "DEBUG": True,
    "SECRET_KEY": "only-development-secret-key",
}


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def add_arguments(self, parser: "CommandParser") -> None:
        parser.add_argument(
            "-t",
            "--template",
            action="store_true",
            dest="template",
            default=False,
            help="Only dumps keys, without values",
        )
        parser.add_argument(
            "--develop", action="store_true", help="Get values from teh code not from the current environment"
        )
        parser.add_argument(
            "--changed", action="store_true", help="Get values from teh code not from the current environment"
        )

        parser.add_argument(
            "--pattern",
            action="store",
            dest="pattern",
            default="{key}={value}  # {help}",
            help="Check env for variable availability",
        )
        parser.add_argument(
            "--check", action="store_true", dest="check", default=False, help="Check env for variable availability"
        )
        parser.add_argument(
            "--ignore-errors", action="store_true", dest="ignore_errors", default=False, help="Do not fail"
        )

    def handle(self, *args: "Any", **options: "Any") -> None:
        from hope_country_report.config import CONFIG, env, EXPLICIT_SET

        check_failure = False
        pattern = options["pattern"]

        for k, __ in sorted(CONFIG.items()):
            help: str = env.get_help(k)
            default = env.get_default(k)
            if options["check"]:
                if default in EXPLICIT_SET and k not in env.ENVIRON:
                    self.stderr.write(self.style.ERROR(f"- Missing env variable: {k}"))
                    check_failure = True
            else:
                value: Any = env.get_value(k)
                if not options["changed"] or (value != default):
                    self.stdout.write(pattern.format(key=k, value=value, help=help, default=default))

        if check_failure and not options["ignore_errors"]:
            raise CommandError("Env check command failure!")
