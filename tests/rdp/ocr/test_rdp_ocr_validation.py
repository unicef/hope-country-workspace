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
    assert isinstance(result["documents"][0]["match"][1], float)
    assert result["documents"][1]["found"] is False
    assert result["documents"][2]["status"] == "error"
    assert result["issues"] == []


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
    ],
)
def test_validate_ocr_result_rejects_invalid_payload(
    payload: object,
    exception: type[Exception],
    match: str,
) -> None:
    with pytest.raises(exception, match=match):
        validate_ocr_result(payload)


@pytest.mark.parametrize(
    ("document", "individual_id", "match"),
    [
        (
            {"individual_id": 0, "status": "ok", "found": False, "match": None, "error": None},
            None,
            "must be positive",
        ),
        (
            {"individual_id": 1, "status": "invalid", "found": False, "match": None, "error": None},
            1,
            "status",
        ),
        (
            {"individual_id": 1, "status": "ok", "found": True, "match": None, "error": None},
            1,
            "inconsistent",
        ),
        (
            {"individual_id": 1, "status": "ok", "found": True, "match": ["ID-1", -1], "error": None},
            1,
            "negative",
        ),
        (
            {"individual_id": 1, "status": "ok", "found": True, "match": ["ID-1"], "error": None},
            1,
            "two items",
        ),
        (
            {"individual_id": 1, "status": "ok", "found": True, "match": [1, 0.1], "error": None},
            1,
            "string, number",
        ),
        (
            {"individual_id": 1, "status": "ok", "found": True, "match": "ID-1", "error": None},
            1,
            "expected list or null",
        ),
        (
            {"individual_id": 1, "status": "ok", "found": "yes", "match": None, "error": None},
            1,
            "invalid field types",
        ),
        (
            {"status": "ok", "found": False, "match": None, "error": None},
            None,
            "missing keys: individual_id",
        ),
    ],
)
def test_validate_ocr_result_isolates_invalid_documents(
    document: dict[str, object],
    individual_id: int | None,
    match: str,
) -> None:
    valid = {"individual_id": 7, "status": "ok", "found": False, "match": None, "error": None}

    result = validate_ocr_result(_payload(documents=[document, valid]))

    assert [item["individual_id"] for item in result["documents"]] == [7]
    assert result["issues"][0]["individual_id"] == individual_id
    assert match in result["issues"][0]["reason"]


def test_validate_ocr_result_keeps_first_document_when_individual_id_is_duplicated() -> None:
    document = {"individual_id": 1, "status": "ok", "found": False, "match": None, "error": None}

    result = validate_ocr_result(_payload(documents=[document, document]))

    assert result["documents"] == [document]
    assert result["issues"] == [
        {"individual_id": 1, "reason": "OCR result documents[1]: duplicate individual_id"},
    ]
