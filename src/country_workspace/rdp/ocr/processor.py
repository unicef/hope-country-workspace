from collections.abc import Iterable, Iterator

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES
from country_workspace.models import Individual, RdpOperationUnit

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
        if extract_base64_content(individual.flex_fields.get(f"{document_type}_image")) is not None:
            return {"document_type": document_type}
    return None


def iter_ocr_unit_configs(individuals: Iterable[Individual]) -> Iterator[tuple[int, OcrUnitConfig]]:
    """Yield stable OCR unit configurations."""
    for individual in individuals:
        if config := get_ocr_unit_config(individual):
            yield individual.pk, config


def build_ocr_document_request(unit: RdpOperationUnit) -> OcrDocumentRequest | None:
    """Build an OCR request from a persisted operation unit."""
    if (document_type := unit.config.get("document_type")) not in DOCUMENT_TYPES:
        return None

    fields = unit.individual.flex_fields
    pattern = fields.get(f"{document_type}_document_number")
    content = extract_base64_content(fields.get(f"{document_type}_image"))

    if not (isinstance(pattern, str) and (pattern := pattern.strip()) and content):
        return None

    return {"individual_id": unit.individual_id, "content": content, "pattern": pattern}
