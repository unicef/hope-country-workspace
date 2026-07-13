import base64
import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from azure.core.exceptions import AzureError
from django.core.files.base import ContentFile

from country_workspace.exceptions import BlobStorageError
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_fields import Base64ImageField

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.models.base import Validable
    from country_workspace.models.mixins import HopeBlobMixin

PREFIX = "data:"


def is_data_uri(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX) and ";base64," in value


def decode_data_uri(value: str) -> bytes:
    return base64.b64decode(value.partition(";base64,")[2])


def image_field_names(checker: "DataChecker") -> list[str]:
    return [
        fs.prefix % field.name if "%s" in fs.prefix else f"{fs.prefix}{field.name}"
        for fs, field in checker.get_fields()
        if field.base_type() == Base64ImageField.__name__
    ]


def sync_record_blobs(
    record: "Validable | HopeBlobMixin",
    image_fields: Sequence[str],
    only: set[str] | None = None,
) -> dict[str, str]:
    """Reconcile record images with the shared HOPE blob storage.

    Raises BlobStorageError when the storage backend is unreachable or fails.
    """
    try:
        return _sync_record_blobs(record, image_fields, only)
    except (AzureError, OSError) as e:
        raise BlobStorageError(
            f"blob sync failed for {type(record).__name__} #{record.pk}: {e.__class__.__name__}: {e}"
        ) from e


def _sync_record_blobs(
    record: "Validable | HopeBlobMixin",
    image_fields: Sequence[str],
    only: set[str] | None,
) -> dict[str, str]:
    hashes = dict(record.blob_hashes or {})
    result: dict[str, str] = {}
    present: set[str] = set()

    for name in image_fields:
        if only is not None and name not in only:
            continue
        value = record.flex_fields.get(name)
        if not is_data_uri(value):
            continue
        present.add(name)
        key = record.hope_blob_key(name)
        new_hash = hashlib.sha256(value.encode()).hexdigest()
        if hashes.get(name) != new_hash:
            if HOPE_STORAGE.exists(key):
                HOPE_STORAGE.delete(key)
            HOPE_STORAGE.save(key, ContentFile(decode_data_uri(value)))
            hashes[name] = new_hash
        result[name] = key

    for name in list(hashes):
        if name not in present and (only is None or name in only):
            HOPE_STORAGE.delete(record.hope_blob_key(name))
            del hashes[name]

    if hashes != (record.blob_hashes or {}):
        record.blob_hashes = hashes
        type(record).objects.filter(pk=record.pk).update(blob_hashes=hashes)
    return result


def substitute_row_images(record: "Validable", row: dict, paths: dict[str, str]) -> dict:
    def repl(name: str, value: Any) -> Any:
        return paths.get(name, value) if is_data_uri(value) else value

    out = {}
    for key, value in row.items():
        if isinstance(value, list):
            out[key] = [
                {k: repl(f"{(it.get('type') or key)}_{k}", v) for k, v in it.items()} if isinstance(it, dict) else it
                for it in value
            ]
        else:
            out[key] = repl(key, value)
    return out
