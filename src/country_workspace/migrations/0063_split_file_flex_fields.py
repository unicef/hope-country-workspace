from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from typing import Any

from django import forms
from django.db import migrations, models
from django.db.migrations.state import StateApps  # noqa: TC002
from django.db.backends.base.schema import BaseDatabaseSchemaEditor  # noqa: TC002
import msgpack

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def _decode_blob(blob: bytes | memoryview | bytearray | None) -> dict[str, Any]:
    if not blob:
        return {}
    raw = bytes(blob) if isinstance(blob, memoryview | bytearray) else blob
    try:
        parsed = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    except (msgpack.ExtraData, msgpack.FormatError, msgpack.StackError, ValueError, TypeError):
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _encode_blob(value: dict[str, Any]) -> bytes | None:
    if not value:
        return None
    return msgpack.packb(dict(sorted(value.items())), use_bin_type=True)


def _checksum(flex_fields: dict[str, Any], flex_files: bytes | None, removed: bool) -> str:
    hasher = hashlib.md5()  # noqa: S324
    hasher.update(json.dumps(flex_fields, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if flex_files:
        hasher.update(memoryview(flex_files))
    hasher.update(bytes([1 if removed else 0]))
    return hasher.hexdigest()


def _is_file_field_type(field_type: Any) -> bool:
    if isinstance(field_type, type):
        try:
            return issubclass(field_type, forms.FileField)
        except TypeError:
            return False
    if isinstance(field_type, str):
        return "FileField" in field_type
    return False


def _fieldset_file_field_names(apps: StateApps) -> dict[int, set[str]]:
    Fieldset = apps.get_model("hope_flex_fields", "Fieldset")
    FieldDefinition = apps.get_model("hope_flex_fields", "FieldDefinition")
    FlexField = apps.get_model("hope_flex_fields", "FlexField")

    definition_is_file = {
        definition.id: _is_file_field_type(definition.field_type)
        for definition in FieldDefinition.objects.only("id", "field_type").iterator()
    }
    if not any(definition_is_file.values()):
        return {}

    fields_by_fieldset: dict[int, list[tuple[str, bool]]] = defaultdict(list)
    for flex_field in FlexField.objects.only("fieldset_id", "name", "definition_id").iterator():
        fields_by_fieldset[flex_field.fieldset_id].append(
            (flex_field.name, definition_is_file.get(flex_field.definition_id, False))
        )

    extends_by_fieldset = {
        fieldset.id: fieldset.extends_id for fieldset in Fieldset.objects.only("id", "extends_id").iterator()
    }
    all_fieldset_ids = set(extends_by_fieldset) | set(fields_by_fieldset)
    resolved: dict[int, dict[str, bool]] = {}

    def _resolve_effective_fields(fieldset_id: int, trail: set[int]) -> dict[str, bool]:
        if fieldset_id in resolved:
            return resolved[fieldset_id]
        if fieldset_id in trail:
            return {}

        parent_id = extends_by_fieldset.get(fieldset_id)
        effective: dict[str, bool] = {}
        if parent_id:
            effective.update(_resolve_effective_fields(parent_id, trail | {fieldset_id}))
        effective.update(dict(fields_by_fieldset.get(fieldset_id, [])))

        resolved[fieldset_id] = effective
        return effective

    by_fieldset: dict[int, set[str]] = {}
    for fieldset_id in all_fieldset_ids:
        names = {name for name, is_file in _resolve_effective_fields(fieldset_id, set()).items() if is_file}
        if names:
            by_fieldset[fieldset_id] = names
    return by_fieldset


def _checker_file_field_names(apps: StateApps) -> dict[int, set[str]]:
    DataCheckerFieldset = apps.get_model("hope_flex_fields", "DataCheckerFieldset")
    fields_by_fieldset = _fieldset_file_field_names(apps)
    if not fields_by_fieldset:
        return {}

    checker_fields: dict[int, set[str]] = defaultdict(set)
    for member in DataCheckerFieldset.objects.only("checker_id", "fieldset_id", "prefix").iterator():
        names = fields_by_fieldset.get(member.fieldset_id, set())
        if not names:
            continue
        prefix = member.prefix or ""
        if "%s" in prefix:
            checker_fields[member.checker_id].update(prefix % name for name in names)
        else:
            checker_fields[member.checker_id].update(f"{prefix}{name}" for name in names)
    return checker_fields


def _flush(model: type[models.Model], pending: list[models.Model]) -> int:
    if not pending:
        return 0
    model.objects.bulk_update(pending, ["flex_fields", "flex_files", "checksum"], batch_size=BATCH_SIZE)
    flushed = len(pending)
    pending.clear()
    return flushed


def _migrate_model_records(
    model: type[models.Model], checker_field_map: dict[int, set[str]], checker_attr: str
) -> None:
    queryset = model.objects.select_related("batch__program").only(
        "id",
        "flex_fields",
        "flex_files",
        "checksum",
        "removed",
        "batch__program__household_checker_id",
        "batch__program__individual_checker_id",
    )
    pending: list[models.Model] = []
    processed = 0
    updated = 0
    for record in queryset.iterator(chunk_size=BATCH_SIZE):
        processed += 1
        checker_id = getattr(record.batch.program, checker_attr)
        file_fields = checker_field_map.get(checker_id, set())
        if not file_fields:
            continue

        flex_fields = dict(record.flex_fields or {})
        files_map = _decode_blob(record.flex_files)
        changed = False

        for field_name in file_fields:
            if field_name not in flex_fields:
                continue

            value = flex_fields.pop(field_name)
            if isinstance(value, str) and value.strip() and field_name not in files_map:
                files_map[field_name] = value
            changed = True

        if not changed:
            continue

        blob = _encode_blob(files_map)
        record.flex_fields = flex_fields
        record.flex_files = blob
        record.checksum = _checksum(flex_fields, blob, bool(record.removed))
        pending.append(record)

        if len(pending) >= BATCH_SIZE:
            updated += _flush(model, pending)
            logger.info("%s: processed=%s updated=%s", model.__name__, processed, updated)

    updated += _flush(model, pending)
    logger.info("%s: migration complete processed=%s updated=%s", model.__name__, processed, updated)


def split_file_flex_fields(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Household = apps.get_model("country_workspace", "Household")
    Individual = apps.get_model("country_workspace", "Individual")

    checker_fields = _checker_file_field_names(apps)
    if not checker_fields:
        return

    _migrate_model_records(Household, checker_fields, "household_checker_id")
    _migrate_model_records(Individual, checker_fields, "individual_checker_id")


class Migration(migrations.Migration):
    dependencies = [
        ("country_workspace", "0062_remove_rdp_uniq_open_rdp_per_program_and_more"),
    ]
    atomic = False
    operations = [
        migrations.RunPython(split_file_flex_fields, migrations.RunPython.noop),
    ]
