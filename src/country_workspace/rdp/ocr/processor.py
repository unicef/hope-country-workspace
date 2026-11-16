from collections.abc import Iterable, Iterator

from hope_flex_fields.references import parse_reference

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES
from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models import Individual, RdpOperationUnit
from country_workspace.services.hope_blob import sync_record_blobs

from .constants import DATA_URI_BASE64_MARKER
from .types import OcrDocumentRequest, OcrUnitConfig


def extract_base64_content(value: object) -> str | None:
    """Return base64 content from a data URI."""
    if not (isinstance(value, str) and value.startswith("data:") and DATA_URI_BASE64_MARKER in value):
        return None
    return value.partition(DATA_URI_BASE64_MARKER)[2] or None


def get_ocr_unit_config(individual: Individual) -> OcrUnitConfig | None:
    """Return the first OCR-ready document configuration."""
    for document_type in DOCUMENT_TYPES:
        pattern = individual.flex_fields.get(f"{document_type}_document_number")
        if not (isinstance(pattern, str) and pattern.strip()):
            continue

        image = individual.flex_fields.get(f"{document_type}_image")
        if parse_reference(image) is not None or extract_base64_content(image) is not None:
            return {"document_type": document_type}
    return None


def iter_ocr_unit_configs(individuals: Iterable[Individual]) -> Iterator[tuple[int, OcrUnitConfig]]:
    """Yield stable OCR unit configurations."""
    for individual in individuals:
        if config := get_ocr_unit_config(individual):
            yield individual.pk, config


def build_ocr_document_request(unit: RdpOperationUnit) -> OcrDocumentRequest | None:
    """Upload the unit document image to the HOPE storage and build an OCR request pointing at it.

    Raises BlobStorageError when the storage backend is unreachable or fails.
    """
    if (document_type := unit.config.get("document_type")) not in DOCUMENT_TYPES:
        return None

    pattern = unit.individual.flex_fields.get(f"{document_type}_document_number")
    if not (isinstance(pattern, str) and (pattern := pattern.strip())):
        return None

    image_field = f"{document_type}_image"
    try:
        filename = sync_record_blobs(unit.individual, [image_field], only={image_field}).get(image_field)
    except MissingFlexFileError:
        return None

    if not filename:
        return None

    return {"individual_id": unit.individual_id, "filename": filename, "pattern": pattern}
