from typing import Any, TYPE_CHECKING

import json
import logging

from django.core.management import BaseCommand

from hope_country_report.apps.core.models import CountryShape
from hope_country_report.utils.media import resource_path

if TYPE_CHECKING:
    ...

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        MAPPING = list(CountryShape.objects.values("name", "un", "iso2", "iso3"))
        _in = resource_path("apps/charts/data/_topology.json")
        data = json.load(_in.open("r"))
        for entry in data["objects"]["countries"]["geometries"]:
            try:
                name = [k for k in MAPPING if k["un"] == int(entry["id"])]
                if name:
                    entry["properties"] = {
                        "name": name[0]["name"],
                        "slug": name[0]["slug"],
                        "iso2": name[0]["iso2"],
                        "iso3": name[0]["iso3"],
                    }
                else:
                    entry["properties"] = {
                        "name": "",
                        "iso2": "",
                        "iso3": "",
                    }
                    print("Unknown ", entry["id"])
            except Exception:
                raise
        _out = resource_path("apps/charts/data/topology.json")
        json.dump(data, _out.open("w"))
