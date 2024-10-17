from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, no_translations
from django.utils.timezone import now

import country_workspace
from country_workspace.versioning.management.manager import Manager

VERSION_TEMPLATE = """# Generated by HCW %(version)s on %(today)s
from packaging.version import Version

_script_for_version = Version("%(version)s")


def forward():
    pass


def backward():
    pass


class Scripts:
    operations = [(forward, backward)]
"""


class Command(BaseCommand):
    help = "Creates new version for apps."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("list", help="Show applied/available scripts")

        parser_create = subparsers.add_parser("create", help="Create a new empty script")
        parser_create.add_argument("--label", help="name of the new script", metavar="LABEL")

        parser_apply = subparsers.add_parser("apply", help="Apply scripts")
        parser_apply.add_argument(
            "num",
            nargs="?",
            help='Scripts will be applied to the one after that selected. Use the name "zero" to unapply all scripts.',
        )
        parser_apply.add_argument(
            "--fake", action="store_true", help="Mark script as run without actually running them."
        )

    @no_translations
    def handle(self, command, label=None, num=None, fake=None, zero=False, **options):
        m = Manager()
        if command == "list":
            for entry in m.existing:
                stem = Path(entry).stem
                x = "x" if m.is_processed(entry) else " "
                self.stdout.write("[{x}] {name}".format(x=x, name=stem))
        elif command == "create":
            new_ver = m.max_version + 1
            ts = now().strftime("%Y_%m_%d_%H%M%S")
            today = now().strftime("%Y %m %d %H:%M:%S")

            dest_file = m.folder / "{:>04}_{}.py".format(new_ver, label or ts)
            with dest_file.open("w") as f:
                f.write(VERSION_TEMPLATE % {"timestamp": ts, "version": country_workspace.VERSION, "today": today})
            if options["verbosity"] > 0:
                self.stdout.write(f"Created script {dest_file.name}")

        elif command == "apply":
            if num == "zero":
                m.zero(out=self.stdout)
            else:
                if not num:
                    num = m.max_version
                else:
                    num = int(num)
                if num >= m.max_applied_version:
                    m.forward(num, fake, self.stdout)
                else:
                    m.backward(num, self.stdout)
        else:
            raise CommandError("Invalid command")
