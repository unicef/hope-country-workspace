import base64
import binascii
import hashlib
import mimetypes
from collections.abc import Collection, Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from azure.core.exceptions import AzureError
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile

from country_workspace.contrib.hope.constants import (
    ACCOUNT_ATTACHMENT_EXTENSIONS,
    ACCOUNT_ATTACHMENT_LIMIT,
    ACCOUNT_ATTACHMENT_SIZE_LIMIT,
)
from country_workspace.exceptions import BlobStorageError, InvalidAccountAttachmentError, MissingFlexFileError
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.account_attachments import attachment_title, iter_attachment_fields
from country_workspace.utils.flex_files import load_flex_files

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.models.base import Validable
    from country_workspace.models.mixins import HopeBlobMixin

PREFIX = "data:"
# hope_blob_key() reads record.country_office and record.program; join them once per query.
RECORD_SELECT_RELATED = "batch__program__country_office"


def is_data_uri(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX) and ";base64," in value


def decode_data_uri(value: str) -> bytes:
    return base64.b64decode(value.partition(";base64,")[2], validate=True)


def image_field_names(checker: "DataChecker") -> set[str]:
    return checker.get_file_field_names()


def sync_record_blobs(
    record: "Validable | HopeBlobMixin",
    image_fields: Collection[str],
    only: set[str] | None = None,
) -> dict[str, str]:
    """Reconcile record images with the shared HOPE blob storage.

    Handles both an offloaded `FlexFieldFile` reference and a legacy inline
    data-URI, and returns the blob key for every image field that has a value.

    Raises BlobStorageError when the storage backend is unreachable or fails,
    or when a flex-field contains a malformed base64 payload. Raises
    MissingFlexFileError when a flex-field references a file row the record
    does not own.
    """
    try:
        return _sync_record_blobs(record, image_fields, only)
    except (AzureError, OSError, binascii.Error) as e:
        raise BlobStorageError(
            f"blob sync failed for {type(record).__name__} #{record.pk}: {e.__class__.__name__}: {e}"
        ) from e


def _sync_record_blobs(
    record: "Validable | HopeBlobMixin",
    image_fields: Collection[str],
    only: set[str] | None,
) -> dict[str, str]:
    hashes = dict(record.blob_hashes or {})
    result: dict[str, str] = {}
    present: set[str] = set()
    names = [name for name in image_fields if only is None or name in only]

    # Reference fields are loaded together up front, so a record with several
    # offloaded image fields costs one query instead of one per field.
    reference_ids = {
        name: file_id
        for name in names
        if (file_id := FlexFieldFile.parse_reference(record.flex_fields.get(name))) is not None
    }
    files = load_flex_files(record, set(reference_ids.values())) if reference_ids else {}

    for name in names:
        value = record.flex_fields.get(name)
        if name in reference_ids:
            if (flex_file := files.get(reference_ids[name])) is None:
                raise MissingFlexFileError(
                    f"{type(record).__name__} #{record.pk}: field {name!r} references missing file {value}"
                )
            new_hash = flex_file.checksum
            content = flex_file.content_bytes
        elif is_data_uri(value):
            content = decode_data_uri(value)
            new_hash = hashlib.sha256(content).hexdigest()
        else:
            continue

        present.add(name)
        key = record.hope_blob_key(name)
        if hashes.get(name) != new_hash:
            # HOPE_STORAGE must be configured with overwrite semantics (enforced by
            # checks.py E004), so save() replaces any existing blob under the same key.
            HOPE_STORAGE.save(key, ContentFile(content))
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


type AttachmentItems = list[dict[str, str]]


def sync_account_attachments(record: "Validable | HopeBlobMixin") -> dict[str, AttachmentItems | None]:
    """Upload the account attachments of `record` to the shared HOPE storage.

    Returns every `{type}_attachments` field with its files replaced by their storage names,
    or None when the field has no file. The storage name follows the immutable file row, so a
    retried push finds the file an earlier attempt uploaded and reuses it. Uploaded files are
    never deleted, because HOPE may already refer to them.

    Raises MissingFlexFileError when an attachment is not a file the record owns,
    InvalidAccountAttachmentError when HOPE would reject it, and BlobStorageError when the
    storage backend is unreachable or fails.
    """
    fields = dict(iter_attachment_fields(record.flex_fields or {}))
    if not fields:
        return {}
    try:
        return _sync_account_attachments(record, fields)
    except (AzureError, OSError) as e:
        raise BlobStorageError(
            f"attachment upload failed for {type(record).__name__} #{record.pk}: {e.__class__.__name__}: {e}"
        ) from e


def _attachment_file(item: Any) -> Any:
    return item.get("file") if isinstance(item, Mapping) else item


def _sync_account_attachments(
    record: "Validable | HopeBlobMixin", fields: dict[str, list[Any]]
) -> dict[str, AttachmentItems | None]:
    file_ids = {
        file_id
        for items in fields.values()
        for item in items
        if (file_id := FlexFieldFile.parse_reference(_attachment_file(item))) is not None
    }
    # Content is deferred: only files missing from the storage are read, one at a time.
    files = {
        flex_file.pk: flex_file
        for flex_file in FlexFieldFile.objects.filter(
            content_type=ContentType.objects.get_for_model(record, for_concrete_model=True),
            object_id=record.pk,
            pk__in=file_ids,
        )
    }
    result: dict[str, AttachmentItems | None] = {}
    for name, items in fields.items():
        stored: AttachmentItems = []
        for item in items:
            if not (file := _attachment_file(item)):
                continue
            if (flex_file := files.get(FlexFieldFile.parse_reference(file))) is None:
                raise MissingFlexFileError(
                    f"{type(record).__name__} #{record.pk}: field {name!r} references missing file {file}"
                )
            key = record.hope_attachment_key(flex_file.pk, _attachment_extension(record, name, flex_file))
            if not HOPE_STORAGE.exists(key):
                content = FlexFieldFile.objects.with_content().get(pk=flex_file.pk).content_bytes
                key = HOPE_STORAGE.save(key, ContentFile(content))
            title = (item.get("title") if isinstance(item, Mapping) else None) or attachment_title(
                flex_file.original_filename
            )
            stored.append({"file": key, "title": title})
        if len(stored) > ACCOUNT_ATTACHMENT_LIMIT:
            raise InvalidAccountAttachmentError(
                f"{type(record).__name__} #{record.pk}: field {name!r} has {len(stored)} attachments, "
                f"HOPE accepts at most {ACCOUNT_ATTACHMENT_LIMIT}"
            )
        result[name] = stored or None
    return result


def _attachment_extension(record: "Validable | HopeBlobMixin", name: str, flex_file: FlexFieldFile) -> str:
    """Return the extension of `flex_file` among those HOPE accepts, checking its size on the way."""
    subject = f"{type(record).__name__} #{record.pk}: field {name!r} file {flex_file.reference}"
    if flex_file.size > ACCOUNT_ATTACHMENT_SIZE_LIMIT:
        raise InvalidAccountAttachmentError(
            f"{subject} is {flex_file.size} bytes, HOPE accepts at most {ACCOUNT_ATTACHMENT_SIZE_LIMIT}"
        )
    candidates = (
        PurePosixPath(flex_file.original_filename or "").suffix,
        mimetypes.guess_extension(flex_file.mimetype or "") or "",
    )
    for suffix in candidates:
        if (extension := suffix.lower().lstrip(".")) in ACCOUNT_ATTACHMENT_EXTENSIONS:
            return f".{extension}"
    raise InvalidAccountAttachmentError(
        f"{subject} ({flex_file.original_filename or flex_file.mimetype}) is not one of the file types HOPE "
        f"accepts: {', '.join(ACCOUNT_ATTACHMENT_EXTENSIONS)}"
    )
