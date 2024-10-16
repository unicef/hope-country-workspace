import re
from pathlib import Path

from django.core.management.base import BaseCommand, no_translations

from country_workspace.versioning.models import Version

regex = re.compile(r"(\d+).*")


def get_version(filename):
    if m := regex.match(filename):
        return int(m.group(1))
    return None


class Command(BaseCommand):
    help = "Creates new version for apps."

    def add_arguments(self, parser):
        parser.add_argument(
            "num",
            nargs="?",
            help="Specify the version label",
        )

    @no_translations
    def handle(self, *app_labels, **options):
        folder = Path(__file__).parent.parent.parent / "versions"
        existing = {}
        applied = list(Version.objects.order_by("name").values_list("name", flat=True))
        for filename in sorted(folder.iterdir()):
            if ver := get_version(filename.name):
                existing[ver] = filename.name
        for filename in existing.values():
            if filename in applied:
                print(f"[x] {filename}")
            else:
                print(f"[ ] {filename}")
