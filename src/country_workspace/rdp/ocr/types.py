from typing import ReadOnly, TypedDict


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
