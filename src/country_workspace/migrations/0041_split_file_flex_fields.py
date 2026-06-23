from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from django.db import migrations, models
from django.db.migrations.state import StateApps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

FLEX_FILES_PREFIX = 8192


def _decode_blob(blob: bytes | memoryview | bytearray | None) -> dict[str, str]:
    if not blob:
        return {}
    raw = bytes(blob) if isinstance(blob, memoryview | bytearray) else blob
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _encode_blob(value: dict[str, str]) -> bytes | None:
    if not value:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _checksum(flex_fields: dict[str, Any], flex_files: bytes | None, removed: bool) -> str:
    hasher = hashlib.md5()  # noqa: S324
    hasher.update(json.dumps(flex_fields, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if flex_files:
        hasher.update(memoryview(flex_files)[:FLEX_FILES_PREFIX])
    hasher.update(bytes([1 if removed else 0]))
    return hasher.hexdigest()


def _checker_file_field_names(apps: StateApps) -> dict[int, set[str]]:
    FieldDefinition = apps.get_model("hope_flex_fields", "FieldDefinition")
    FlexField = apps.get_model("hope_flex_fields", "FlexField")
    DataCheckerFieldset = apps.get_model("hope_flex_fields", "DataCheckerFieldset")

    file_definition_ids = {
        definition.id
        for definition in FieldDefinition.objects.only("id", "field_type").iterator()
        if "Base64ImageField" in str(definition.field_type)
    }
    if not file_definition_ids:
        return {}

    fields_by_fieldset: dict[int, set[str]] = defaultdict(set)
    for flex_field in (
        FlexField.objects.filter(definition_id__in=file_definition_ids).only("fieldset_id", "name").iterator()
    ):
        fields_by_fieldset[flex_field.fieldset_id].add(flex_field.name)

    checker_fields: dict[int, set[str]] = defaultdict(set)
    for member in DataCheckerFieldset.objects.only("checker_id", "fieldset_id", "prefix").iterator():
        names = fields_by_fieldset.get(member.fieldset_id, set())
        if not names:
            continue
        prefix = member.prefix or ""
        checker_fields[member.checker_id].update(f"{prefix}{name}" for name in names)
    return checker_fields


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
    for record in queryset.iterator():
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
        record.save(update_fields=["flex_fields", "flex_files", "checksum"])


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
        ("country_workspace", "0040_add_originating_id_to_validable"),
    ]
    atomic = False
    operations = [
        migrations.RunPython(split_file_flex_fields, migrations.RunPython.noop),
    ]
