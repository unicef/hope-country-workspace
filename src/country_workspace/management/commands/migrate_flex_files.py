from argparse import ArgumentParser
from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import Generator
import re
from typing import Any

from django.core.management import BaseCommand
from django.db import transaction

from country_workspace.models import Household, Individual
from country_workspace.models.base import Validable
from country_workspace.utils.flex_fields import get_obj_checksum
from country_workspace.utils.flex_files import DATA_URI_PREFIX, DEFAULT_MIMETYPE, write_flex_file

DEFAULT_BATCH_SIZE = 200
DATA_URI_RE = re.compile(r"^data:(?P<mimetype>[^;,]*);base64,(?P<content>.*)$", re.DOTALL)


def parse_data_uri(value: Any) -> tuple[str, bytes] | None:
    if not isinstance(value, str) or not value.startswith(DATA_URI_PREFIX):
        return None
    if not (match := DATA_URI_RE.match(value)):
        return None
    try:
        content = b64decode(match.group("content"), validate=True)
    except (BinasciiError, ValueError):
        return None
    return match.group("mimetype") or DEFAULT_MIMETYPE, content


class Command(BaseCommand):
    help = "Move inline base64 flex field files into the FlexFieldFile table."
    requires_migrations_checks = False
    requires_system_checks = []

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, dest="batch_size")
        parser.add_argument(
            "--start-pk",
            type=int,
            default=0,
            dest="start_pk",
            help="Resume after this primary key",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        for model in (Household, Individual):
            converted = self._convert(model, options["batch_size"], options["start_pk"])
            self.stdout.write("%s: converted %d record(s)" % (model._meta.model_name, converted))

    def _convert(self, model: type[Validable], batch_size: int, start_pk: int) -> int:
        converted = 0
        for batch in self._batches(model, batch_size, start_pk):
            for record in batch:
                if self._convert_record(record):
                    converted += 1
        return converted

    def _batches(self, model: type[Validable], batch_size: int, start_pk: int) -> Generator[list[Validable]]:
        last_pk = start_pk
        while True:
            batch = list(model.objects.all().filter(pk__gt=last_pk).order_by("pk")[:batch_size])
            if not batch:
                return
            yield batch
            last_pk = batch[-1].pk

    def _convert_record(self, record: Validable) -> bool:
        flex_fields = dict(record.flex_fields or {})
        raw_data = dict(record.raw_data or {})
        # one row per distinct content, even when flex_fields and raw_data key it differently
        references: dict[str, str] = {}

        with transaction.atomic():
            for payload in (flex_fields, raw_data):
                for name, value in payload.items():
                    if (parsed := parse_data_uri(value)) is None:
                        continue
                    if value not in references:
                        mimetype, content = parsed
                        references[value] = write_flex_file(record, name, content, mimetype)
                    payload[name] = references[value]

            if not references:
                return False

            record.flex_fields = flex_fields
            record.raw_data = raw_data
            type(record).objects.filter(pk=record.pk).update(
                flex_fields=flex_fields,
                raw_data=raw_data,
                checksum=get_obj_checksum(record),
            )
        return True
