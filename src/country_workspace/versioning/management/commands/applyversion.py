from django.core.management.base import BaseCommand, no_translations

from country_workspace.versioning.management.manager import Manager


class Command(BaseCommand):
    help = "Creates new version for apps."

    def add_arguments(self, parser):
        parser.add_argument("num", nargs="?", help="Specify the version label")

    @no_translations
    def handle(self, num, **options):
        m = Manager()
        if not num:
            num = m.max_version
        print(f"Available update {m.max_version}")
        print(f"Applied update {m.max_applied_version}")
        if num == "zero":
            m.zero()
        else:
            num = int(num)
            if not num:
                num = m.max_applied_version
            if num >= m.max_applied_version:
                m.forward(num)
