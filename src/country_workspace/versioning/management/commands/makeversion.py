import re
from pathlib import Path

from django.core.management.base import BaseCommand, no_translations
from django.utils.timezone import now

import country_workspace

VERSION_TEMPLATE = """# Generated by HCW %(version)s on %(timestamp)s

class Version:
    operations = []
"""

regex = re.compile(r"(\d+).*")


def get_version(filename):
    if m := regex.match(filename):
        return int(m.group(1))
    return None


ts = now().strftime("%Y_%m_%d_%H%M%S")


class Command(BaseCommand):
    help = "Creates new version"

    def add_arguments(self, parser):
        parser.add_argument(
            "label",
            nargs="?",
            help="Specify the version label",
        )

    @no_translations
    def handle(self, label, **options):
        folder = Path(__file__).parent.parent.parent / "versions"
        last_ver = 0
        for filename in folder.iterdir():
            if ver := get_version(filename.name):
                last_ver = max(last_ver, ver)
        new_ver = last_ver + 1
        dest_file = folder / "{:>04}_{}.py".format(new_ver, label or ts)
        with dest_file.open("w") as f:
            f.write(VERSION_TEMPLATE % {"timestamp": ts, "version": country_workspace.VERSION})
        print(f"Created version {dest_file.name}")