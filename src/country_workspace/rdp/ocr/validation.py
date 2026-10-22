from typing import Literal, cast

from .types import OcrDocumentResult, OcrResultMessage


_DOCUMENT_RESULT_KEYS = ("individual_id", "status", "found", "match", "error")
_RESULT_MESSAGE_KEYS = ("correlation_id", "rdp_id", "batch_id", "batch_index", "batch_total", "documents")


def _object(value: object, *, required: tuple[str, ...], path: str) -> dict[str, object]:
    """Validate a JSON object and its required fields."""
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected object")

    data = cast("dict[str, object]", value)
    if missing := [key for key in required if key not in data]:
        raise ValueError(f"{path}: missing keys: {', '.join(missing)}")
    return data


def _parse_match(value: object, *, path: str) -> list[str | float] | None:
    """Validate and normalize an OCR match."""
    match value:
        case None:
            return None
        case [str() as text, (int() | float()) as distance] if type(distance) in {int, float}:
            if distance < 0:
                raise ValueError(f"{path}: distance must not be negative")
            return [text, float(distance)]
        case list() if len(value) != 2:
            raise ValueError(f"{path}: expected two items")
        case list():
            raise TypeError(f"{path}: expected [string, number]")
        case _:
            raise TypeError(f"{path}: expected list or null")


def _parse_document_result(value: object, *, index: int) -> OcrDocumentResult:
    """Validate and normalize one OCR document result."""
    path = f"OCR result documents[{index}]"
    data = _object(value, required=_DOCUMENT_RESULT_KEYS, path=path)

    match data:
        case {
            "individual_id": int() as individual_id,
            "status": str() as status,
            "found": bool() as found,
            "match": raw_match,
            "error": (None | str()) as error,
        } if type(individual_id) is int:
            pass
        case _:
            raise TypeError(f"{path}: invalid field types")

    if individual_id <= 0:
        raise ValueError(f"{path}.individual_id: must be positive")
    if status not in {"ok", "error"}:
        raise ValueError(f"{path}.status: invalid value")

    result: OcrDocumentResult = {
        "individual_id": individual_id,
        "status": cast("Literal['ok', 'error']", status),
        "found": found,
        "match": _parse_match(raw_match, path=f"{path}.match"),
        "error": error,
    }

    match result["status"], result["found"], result["match"], result["error"]:
        case ("ok", True, [_, _], None) | ("ok", False, None, None) | ("error", False, None, _):
            return result
        case _:
            raise ValueError(f"{path}: inconsistent result")


def validate_ocr_result(payload: object) -> OcrResultMessage:
    """Validate and normalize an OCR result message."""
    data = _object(payload, required=_RESULT_MESSAGE_KEYS, path="OCR result")

    match data:
        case {
            "correlation_id": str() as correlation_id,
            "rdp_id": int() as rdp_id,
            "batch_id": str() as batch_id,
            "batch_index": int() as batch_index,
            "batch_total": int() as batch_total,
            "documents": list() as raw_documents,
        } if all(type(value) is int for value in (rdp_id, batch_index, batch_total)):
            pass
        case _:
            raise TypeError("OCR result: invalid field types")

    if not correlation_id or not batch_id:
        raise ValueError("OCR result: correlation_id and batch_id must not be empty")
    if rdp_id <= 0:
        raise ValueError("OCR result.rdp_id: must be positive")
    if not 1 <= batch_index <= batch_total:
        raise ValueError("OCR result: invalid batch position")
    if not raw_documents:
        raise ValueError("OCR result: documents must not be empty")

    documents = [_parse_document_result(value, index=index) for index, value in enumerate(raw_documents)]
    if len(individual_ids := [document["individual_id"] for document in documents]) != len(set(individual_ids)):
        raise ValueError("OCR result: duplicate individual_id")

    return {
        "correlation_id": correlation_id,
        "rdp_id": rdp_id,
        "batch_id": batch_id,
        "batch_index": batch_index,
        "batch_total": batch_total,
        "documents": documents,
    }
