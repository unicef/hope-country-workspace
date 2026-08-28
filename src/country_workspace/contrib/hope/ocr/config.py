from typing import NotRequired, ReadOnly, TypedDict


class OcrDocumentRequest(TypedDict):
    individual_id: ReadOnly[int]
    filename: ReadOnly[str]
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
    status: str
    found: NotRequired[bool]
    match: NotRequired[list]
    error: NotRequired[str | None]


class OcrResultMessage(TypedDict):
    correlation_id: str
    rdp_id: int
    batch_id: str
    batch_index: int
    batch_total: int
    documents: list[OcrDocumentResult]
