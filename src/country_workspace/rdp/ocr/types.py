from typing import Literal, ReadOnly, TypedDict

from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class OcrUnitConfig(TypedDict):
    document_type: ReadOnly[str]


class OcrDocumentRequest(TypedDict):
    individual_id: ReadOnly[int]
    content: ReadOnly[str]
    pattern: ReadOnly[str]


class OcrRequestMessage(TypedDict):
    correlation_id: ReadOnly[str]
    rdp_id: ReadOnly[int]
    batch_id: ReadOnly[str]
    batch_index: ReadOnly[int]
    batch_total: ReadOnly[int]
    documents: ReadOnly[list[OcrDocumentRequest]]


class OcrDocumentResult(TypedDict):
    individual_id: int
    status: Literal["ok", "error"]
    found: bool
    match: list[str | float] | None
    error: str | None


class OcrResultMessage(TypedDict):
    correlation_id: str
    rdp_id: int
    batch_id: str
    batch_index: int
    batch_total: int
    documents: list[OcrDocumentResult]


class OcrFindingType(TextChoices):
    NO_MATCH = "NO_MATCH", _("No match")
    OCR_ERROR = "OCR_ERROR", _("OCR error")
