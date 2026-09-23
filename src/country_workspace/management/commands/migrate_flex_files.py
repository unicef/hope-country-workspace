from argparse import ArgumentParser
from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import re
from typing import TYPE_CHECKING, Any

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.db.models import BinaryField, Func, Q, TextField, Value
from django.db.models.functions import Cast
from django.template.defaultfilters import filesizeformat

from country_workspace.models import Household, Individual
from country_workspace.models.base import Validable
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.utils.flex_fields import FLEX_FILES_PREFIX, get_obj_checksum
from country_workspace.utils.flex_files import DATA_URI_PREFIX, DEFAULT_MIMETYPE, as_data_uri, write_flex_file

if TYPE_CHECKING:
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 200
DATA_URI_RE = re.compile(r"^data:(?P<mimetype>[^;,]*);base64,(?P<content>.*)$", re.DOTALL)
LOCK_KEY = "lock:migrate_flex_files"
LOCK_EXPIRE = 900
MODELS: dict[str, type[Validable]] = {"household": Household, "individual": Individual}


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


@dataclass
class Stats:
    scanned: int = 0
    changed: int = 0
    files: int = 0
    content_bytes: int = 0
    unreadable: int = 0
    dropped: int = 0
    failed: int = 0
    last_pk: int = 0


class Command(BaseCommand):
    """Move inline base64 flex field files into the `FlexFieldFile` table, or back.

    Meant to be run by hand, after `migrate`, on a database upgraded from a
    release that stored files inline. Converting a record is a single
    transaction, so an interrupted run leaves no half converted record and
    rerunning picks up what is left: already converted records no longer hold
    inline values, and `write_flex_file` reuses a row of identical content.
    """

    help = "Move inline base64 flex field files into the FlexFieldFile table, or back with --reverse."
    requires_migrations_checks = False
    requires_system_checks = []

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--model", choices=(*MODELS, "all"), default="all")
        parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, dest="batch_size")
        parser.add_argument(
            "--start-pk",
            type=int,
            default=0,
            dest="start_pk",
            help="Resume after this primary key, requires an explicit --model",
        )
        parser.add_argument("--limit", type=int, default=0, help="Stop after changing this many records")
        parser.add_argument(
            "--reverse",
            action="store_true",
            help="Write the files back inline and delete them, leaving the table empty",
        )
        parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Report without writing anything")
        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            dest="continue_on_error",
            help="Keep going past a failing record and report the failures at the end",
        )
        parser.add_argument("--no-lock", action="store_true", dest="no_lock", help="Skip the concurrency lock")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["start_pk"] and options["model"] == "all":
            raise CommandError("--start-pk needs an explicit --model")

        self.reverse: bool = options["reverse"]
        self.dry_run: bool = options["dry_run"]
        self.continue_on_error: bool = options["continue_on_error"]
        self.verbosity: int = options["verbosity"]
        self.remaining: int | None = options["limit"] or None
        models = list(MODELS.values()) if options["model"] == "all" else [MODELS[options["model"]]]
        failures: list[str] = []

        with self._lock(no_lock=options["no_lock"]):
            for model in models:
                stats = Stats(last_pk=options["start_pk"])
                try:
                    self._run(model, options["batch_size"], stats, failures)
                finally:
                    self._report(model, stats)
                if self.remaining is not None and self.remaining <= 0:
                    self._resume_hint(model, stats.last_pk, "the limit was reached")
                    break

        if failures:
            raise CommandError("%d record(s) failed: %s" % (len(failures), "; ".join(failures[:10])))

    def _run(self, model: type[Validable], batch_size: int, stats: Stats, failures: list[str]) -> None:
        for batch in self._batches(model, batch_size, stats.last_pk):
            for record in batch:
                stats.scanned += 1
                stats.last_pk = record.pk
                try:
                    changed = self._apply(record, stats)
                except Exception as e:
                    stats.failed += 1
                    failures.append("%s #%s: %s" % (model_name(model), record.pk, e))
                    logger.exception("%s #%s could not be processed", model_name(model), record.pk)
                    if not self.continue_on_error:
                        self._resume_hint(model, record.pk - 1, "#%s failed" % record.pk)
                        raise
                    continue
                if not changed:
                    continue
                stats.changed += 1
                if self.remaining is not None:
                    self.remaining -= 1
                    if self.remaining <= 0:
                        return
            logger.info(
                "%s: scanned %d, changed %d, files %d, at pk %d",
                model_name(model),
                stats.scanned,
                stats.changed,
                stats.files,
                stats.last_pk,
            )
            self._write("%s: at pk %d, changed %d" % (model_name(model), stats.last_pk, stats.changed), min_verbosity=2)
        if self.reverse:
            self._drop_orphan_rows(model, stats)

    def _drop_orphan_rows(self, model: type[Validable], stats: Stats) -> None:
        """Rows left by a record deleted outside the cascade, which nothing can restore."""
        orphans = FlexFieldFile.objects.filter(content_type=content_type_of(model)).exclude(
            object_id__in=model.objects.all().values("pk")
        )
        if self.dry_run:
            stats.dropped += orphans.count()
            return
        stats.dropped += orphans.delete()[0]

    def _batches(self, model: type[Validable], batch_size: int, start_pk: int) -> Generator[list[Validable]]:
        last_pk = start_pk
        while True:
            batch = list(self._candidates(model, last_pk)[:batch_size])
            if not batch:
                return
            last_pk = batch[-1].pk
            yield batch

    def _candidates(self, model: type[Validable], last_pk: int) -> "QuerySet[Validable]":
        if self.reverse:
            # owners come from the file table, so that every row is restored and the table ends up empty
            owner_ids = (
                FlexFieldFile.objects.filter(content_type=content_type_of(model), object_id__gt=last_pk)
                .order_by("object_id")
                .values_list("object_id", flat=True)
                .distinct()
            )
            queryset = model.objects.all().filter(pk__in=owner_ids)
        else:
            # keeping the scan in the database avoids loading every record just to find the few with files
            queryset = (
                model.objects.all()
                .annotate(flex_text=Cast("flex_fields", TextField()), raw_text=Cast("raw_data", TextField()))
                .filter(Q(flex_text__contains=DATA_URI_PREFIX) | Q(raw_text__contains=DATA_URI_PREFIX))
                .filter(pk__gt=last_pk)
            )
        return with_checksum_prefix(queryset).order_by("pk")

    def _apply(self, record: Validable, stats: Stats) -> bool:
        # get_obj_checksum() hashes only the first bytes of the deferred legacy column, so the
        # prefix selected with the record stands in for it and no per record blob fetch happens
        record.flex_files = record.flex_files_prefix
        if self.reverse:
            return self._restore_record(record, stats)
        return self._convert_record(record, stats)

    def _convert_record(self, record: Validable, stats: Stats) -> bool:
        flex_fields = dict(record.flex_fields or {})
        raw_data = dict(record.raw_data or {})
        inline = self._inline_values(record, (flex_fields, raw_data), stats)
        if not inline:
            return False

        stats.files += len(inline)
        stats.content_bytes += sum(len(content) for _, _, content in inline.values())
        if self.dry_run:
            return True

        with transaction.atomic():
            references = {
                value: write_flex_file(record, field_name, content, mimetype)
                for value, (field_name, mimetype, content) in inline.items()
            }
            self._save(record, substitute(flex_fields, references), substitute(raw_data, references))
        return True

    def _restore_record(self, record: Validable, stats: Stats) -> bool:
        rows = {
            row.pk: row
            for row in FlexFieldFile.objects.with_content().filter(
                content_type=content_type_of(type(record)), object_id=record.pk
            )
        }
        if not rows:
            return False

        flex_fields = dict(record.flex_fields or {})
        raw_data = dict(record.raw_data or {})
        data_uris: dict[str, str] = {}
        for payload in (flex_fields, raw_data):
            for field_name, value in payload.items():
                if (file_id := FlexFieldFile.parse_reference(value)) is None:
                    continue
                if (row := rows.get(file_id)) is None:
                    stats.unreadable += 1
                    logger.warning(
                        "%s #%s: field %r references %s, owned by no row",
                        model_name(type(record)),
                        record.pk,
                        field_name,
                        value,
                    )
                    continue
                data_uris[value] = as_data_uri(row)

        stats.files += len(rows)
        stats.content_bytes += sum(row.size for row in rows.values())
        if self.dry_run:
            return True

        with transaction.atomic():
            self._save(record, substitute(flex_fields, data_uris), substitute(raw_data, data_uris))
            # the only place rows are deleted on their own, so that the table can be dropped
            FlexFieldFile.objects.filter(pk__in=list(rows)).delete()
        return True

    def _inline_values(
        self,
        record: Validable,
        payloads: tuple[Mapping[str, Any], ...],
        stats: Stats,
    ) -> dict[str, tuple[str, str, bytes]]:
        """Distinct inline values of the record, mapped to the field they first appear in.

        One row per distinct content, even when `flex_fields` and `raw_data` key
        it differently.
        """
        inline: dict[str, tuple[str, str, bytes]] = {}
        for payload in payloads:
            for field_name, value in payload.items():
                if not isinstance(value, str) or not value.startswith(DATA_URI_PREFIX) or value in inline:
                    continue
                if (parsed := parse_data_uri(value)) is None:
                    stats.unreadable += 1
                    logger.warning(
                        "%s #%s: field %r holds a value that is not a readable data-URI",
                        model_name(type(record)),
                        record.pk,
                        field_name,
                    )
                    continue
                mimetype, content = parsed
                inline[value] = (field_name, mimetype, content)
        return inline

    def _save(self, record: Validable, flex_fields: dict[str, Any], raw_data: dict[str, Any]) -> None:
        record.flex_fields = flex_fields
        record.raw_data = raw_data
        type(record).objects.filter(pk=record.pk).update(
            flex_fields=flex_fields,
            raw_data=raw_data,
            checksum=get_obj_checksum(record),
        )

    def _report(self, model: type[Validable], stats: Stats) -> None:
        self._write(
            "%s%s: %s %d record(s), %d file(s), %s (scanned %d, unreadable %d, failed %d)%s"
            % (
                "[dry-run] " if self.dry_run else "",
                model_name(model),
                "restored" if self.reverse else "converted",
                stats.changed,
                stats.files,
                filesizeformat(stats.content_bytes),
                stats.scanned,
                stats.unreadable,
                stats.failed,
                ", %d orphan row(s) dropped" % stats.dropped if stats.dropped else "",
            )
        )

    def _resume_hint(self, model: type[Validable], last_pk: int, because: str) -> None:
        self._write(
            "%s: %s, resume with --model %s --start-pk %d" % (model_name(model), because, model_name(model), last_pk)
        )

    def _write(self, message: str, min_verbosity: int = 1) -> None:
        if self.verbosity >= min_verbosity:
            self.stdout.write(message)

    @contextmanager
    def _lock(self, *, no_lock: bool) -> Iterator[None]:
        if no_lock:
            yield
            return
        lock = cache.lock(LOCK_KEY, LOCK_EXPIRE, auto_renewal=True)
        if not lock.acquire(blocking=False):
            raise CommandError("another migrate_flex_files run is in progress")
        try:
            yield
        finally:
            lock.release()


def model_name(model: type[Validable]) -> str:
    return model._meta.model_name or model.__name__.lower()


def content_type_of(model: type[Validable]) -> ContentType:
    return ContentType.objects.get_for_model(model, for_concrete_model=True)


def substitute(payload: dict[str, Any], replacements: dict[str, str]) -> dict[str, Any]:
    return {
        field_name: replacements.get(value, value) if isinstance(value, str) else value
        for field_name, value in payload.items()
    }


def with_checksum_prefix(queryset: "QuerySet[Validable]") -> "QuerySet[Validable]":
    return queryset.annotate(
        flex_files_prefix=Func(
            "flex_files",
            Value(1),
            Value(FLEX_FILES_PREFIX),
            function="SUBSTR",
            output_field=BinaryField(),
        )
    )
