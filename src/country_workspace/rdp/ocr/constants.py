from typing import Final

from .types import OcrFindingType


DATA_URI_BASE64_MARKER: Final[str] = ";base64,"
OCR_BATCH_SIZE: Final[int] = 10
OCR_UNIT_BULK_CREATE_BATCH_SIZE: Final[int] = 1000

OCR_AFFECTING_FINDING_TYPES: Final[frozenset[str]] = frozenset(
    {
        OcrFindingType.NO_MATCH.value,
        OcrFindingType.OCR_ERROR.value,
    }
)
