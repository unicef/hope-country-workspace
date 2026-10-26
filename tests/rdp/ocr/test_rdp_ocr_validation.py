import pytest

from country_workspace.rdp.ocr.validation import validate_ocr_result


def _payload(*, documents: list[object] | None = None, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "correlation_id": "correlation",
        "rdp_id": 1,
        "batch_id": "batch",
        "batch_index": 1,
        "batch_total": 1,
        "documents": documents
        if documents is not None
        else [
            {
                "individual_id": 1,
                "status": "ok",
                "found": True,
                "match": ["ID-1", 0],
                "error": None,
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_validate_ocr_result_normalizes_valid_documents() -> None:
    result = validate_ocr_result(
        _payload(
            documents=[
                {
                    "individual_id": 1,
                    "status": "ok",
                    "found": True,
                    "match": ["ID-1", 1],
                    "error": None,
                },
                {
                    "individual_id": 2,
                    "status": "ok",
                    "found": False,
                    "match": None,
                    "error": None,
                },
                {
                    "individual_id": 3,
                    "status": "error",
                    "found": False,
                    "match": None,
                    "error": "OCR failed",
                },
            ]
        )
    )

    assert result["documents"][0]["match"] == ["ID-1", 1.0]
    assert result["documents"][1]["found"] is False
    assert result["documents"][2]["status"] == "error"


@pytest.mark.parametrize(
    ("payload", "exception", "match"),
    [
        (None, TypeError, "expected object"),
        ({"correlation_id": "x"}, ValueError, "missing keys"),
        (_payload(rdp_id=True), TypeError, "invalid field types"),
        (_payload(correlation_id=""), ValueError, "must not be empty"),
        (_payload(rdp_id=0), ValueError, "must be positive"),
        (_payload(batch_index=2, batch_total=1), ValueError, "batch position"),
        (_payload(documents=[]), ValueError, "documents must not be empty"),
        (
            _payload(
                documents=[
                    {"individual_id": 1, "status": "ok", "found": False, "match": None, "error": None},
                    {"individual_id": 1, "status": "ok", "found": False, "match": None, "error": None},
                ]
            ),
            ValueError,
            "duplicate individual_id",
        ),
        (
            _payload(
                documents=[
                    {"individual_id": 0, "status": "ok", "found": False, "match": None, "error": None},
                ]
            ),
            ValueError,
            "must be positive",
        ),
        (
            _payload(
                documents=[
                    {"individual_id": 1, "status": "invalid", "found": False, "match": None, "error": None},
                ]
            ),
            ValueError,
            "status",
        ),
        (
            _payload(
                documents=[
                    {"individual_id": 1, "status": "ok", "found": True, "match": None, "error": None},
                ]
            ),
            ValueError,
            "inconsistent",
        ),
        (
            _payload(
                documents=[
                    {"individual_id": 1, "status": "ok", "found": True, "match": ["ID-1", -1], "error": None},
                ]
            ),
            ValueError,
            "negative",
        ),
        (
            _payload(
                documents=[
                    {"individual_id": 1, "status": "ok", "found": True, "match": ["ID-1"], "error": None},
                ]
            ),
            ValueError,
            "two items",
        ),
        (
            _payload(
                documents=[
                    {"individual_id": 1, "status": "ok", "found": True, "match": [1, 0.1], "error": None},
                ]
            ),
            TypeError,
            "string, number",
        ),
    ],
)
def test_validate_ocr_result_rejects_invalid_payload(
    payload: object,
    exception: type[Exception],
    match: str,
) -> None:
    with pytest.raises(exception, match=match):
        validate_ocr_result(payload)
