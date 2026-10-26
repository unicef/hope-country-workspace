import base64
import mimetypes
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any

from constance import config as constance_config
from django.db import transaction
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError

from country_workspace.models import AsyncJob
from ...models import CountryBatch, CountryIndividual
from ....storages import MEDIA_STORAGE
from ....utils.flex_fields import Base64ImageField


class PictureImportLimitError(ValueError):
    pass


class BatchPictureImportService:
    def __init__(self, batch: CountryBatch) -> None:
        self.batch = batch

    @staticmethod
    def _normalize_match_key(value: object | None) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    @staticmethod
    def _guess_image_mimetype(filename: str, content: bytes) -> str:
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
                image_format = image.format
        except (UnidentifiedImageError, OSError):
            return "application/octet-stream"
        if image_format:
            pil_mime = Image.MIME.get(image_format)
            if pil_mime and pil_mime.startswith("image/"):
                return pil_mime
        guessed, _ = mimetypes.guess_type(filename)
        if guessed and guessed.startswith("image/"):
            return guessed
        return "application/octet-stream"

    @classmethod
    def _validate_archive_limits(cls, archive: zipfile.ZipFile) -> None:
        max_zip_file_count = int(constance_config.PICTURE_IMPORT_MAX_ZIP_FILE_COUNT)
        file_count = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            file_count += 1
            if file_count > max_zip_file_count:
                raise PictureImportLimitError(f"ZIP archive contains too many files (max {max_zip_file_count}).")

    @classmethod
    def extract_zip_images(
        cls, zip_file: UploadedFile, *, include_data_uri: bool = True
    ) -> tuple[list[dict[str, str]], set[str]]:
        entries: list[dict[str, str]] = []
        duplicates: set[str] = set()
        seen_keys: set[str] = set()

        zip_file.seek(0)
        with zipfile.ZipFile(zip_file) as archive:
            cls._validate_archive_limits(archive)
            for info in archive.infolist():
                if info.is_dir():
                    continue
                filename = Path(info.filename).name
                if not filename:
                    continue

                content = archive.read(info)
                mimetype = cls._guess_image_mimetype(filename, content)
                if not mimetype.startswith("image/"):
                    continue

                key = cls._normalize_match_key(Path(filename).stem)
                if not key:
                    continue

                if key in seen_keys:
                    duplicates.add(key)
                    continue
                seen_keys.add(key)

                item: dict[str, str] = {"filename": filename, "key": key}
                if include_data_uri:
                    item["data_uri"] = f"data:{mimetype};base64,{base64.b64encode(content).decode()}"
                entries.append(item)

        zip_file.seek(0)
        return entries, duplicates

    def get_match_field_choices(self) -> list[tuple[str, str]]:
        keys: set[str] = set()
        queryset = CountryIndividual.objects.filter(batch=self.batch, removed=False).values_list("raw_data", flat=True)
        for raw_data in queryset.iterator():
            if isinstance(raw_data, dict):
                keys.update(raw_data.keys())
        return [(key, key) for key in sorted(keys)]

    def get_target_field_choices(self) -> list[tuple[str, str]]:
        checker = self.batch.program.individual_checker
        if not checker:
            return []
        form = checker.get_form()()
        return [
            (field_name, field.label or field_name)
            for field_name, field in form.fields.items()
            if isinstance(field, Base64ImageField)
        ]

    def build_preview(self, match_field: str, zip_file: UploadedFile, include_data_uri: bool = False) -> dict[str, Any]:
        individuals = list(CountryIndividual.objects.filter(batch=self.batch, removed=False).only("id", "raw_data"))
        by_key: defaultdict[str, list[int]] = defaultdict(list)
        for individual in individuals:
            key = self._normalize_match_key((individual.raw_data or {}).get(match_field))
            if key:
                by_key[key].append(individual.id)

        zip_entries, duplicate_zip_keys = self.extract_zip_images(zip_file, include_data_uri=include_data_uri)
        assignments: list[dict[str, Any]] = []
        unmatched_filenames: list[str] = []
        ambiguous_record_keys: set[str] = set()

        for entry in zip_entries:
            if entry["key"] in duplicate_zip_keys:
                continue
            record_ids = by_key.get(entry["key"], [])
            if len(record_ids) == 1:
                assignment = {
                    "record_id": record_ids[0],
                    "record_key": entry["key"],
                    "filename": entry["filename"],
                }
                if include_data_uri:
                    assignment["data_uri"] = entry["data_uri"]
                assignments.append(assignment)
            elif len(record_ids) > 1:
                ambiguous_record_keys.add(entry["key"])
            else:
                unmatched_filenames.append(entry["filename"])

        return {
            "total_picture_files": len(zip_entries),
            "total_records": len(individuals),
            "matched_records_count": len({item["record_id"] for item in assignments}),
            "matched_files_count": len(assignments),
            "duplicate_zip_keys": sorted(duplicate_zip_keys),
            "ambiguous_record_keys": sorted(ambiguous_record_keys),
            "unmatched_filenames": sorted(unmatched_filenames),
            "assignments": assignments,
        }

    def apply_assignments(self, target_field: str, assignments: list[dict[str, Any]]) -> int:
        if not assignments:
            return 0
        record_ids = [item["record_id"] for item in assignments]
        individuals = CountryIndividual.objects.filter(
            pk__in=record_ids,
            batch=self.batch,
            removed=False,
        ).in_bulk()

        updated = 0
        with transaction.atomic():
            for item in assignments:
                individual = individuals.get(item["record_id"])
                if not individual:
                    continue
                current = dict(individual.flex_fields or {})
                current[target_field] = item["data_uri"]
                if current != individual.flex_fields:
                    individual.flex_fields = current
                    individual.last_checked = None
                    individual.errors = {}
                    individual.save(update_fields=["flex_fields", "last_checked", "errors"])
                    updated += 1
        return updated


def import_pictures_for_batch(job: AsyncJob) -> dict[str, int]:
    if not (batch_id := job.config.get("batch_id")):
        raise ValueError("batch_id is required in job config")
    batch = CountryBatch.objects.select_related("program", "country_office").filter(pk=batch_id).first()
    if not batch:
        raise ValueError(f"Batch {batch_id} not found")

    payload = batch.get_picture_import_state()
    if not isinstance(payload, dict):
        raise TypeError("Picture import payload not found")
    match_field = payload.get("match_field")
    target_field = payload.get("target_field")
    zip_file_name = payload.get("zip_file_name")
    if not match_field or not target_field or not zip_file_name:
        raise ValueError("Picture import payload is incomplete")

    service = BatchPictureImportService(batch)
    try:
        with MEDIA_STORAGE.open(zip_file_name, "rb") as zip_stream:
            preview = service.build_preview(match_field, zip_stream, include_data_uri=True)
        updated = service.apply_assignments(target_field, preview.get("assignments", []))
        return {"updated": updated}
    finally:
        # Always clear draft state + temp ZIP after the job run.
        batch.finish_picture_import()
        MEDIA_STORAGE.delete(zip_file_name)
