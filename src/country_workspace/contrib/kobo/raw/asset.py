from typing import TypedDict

class SurveyItem(TypedDict("SurveyItem", {"$xpath": str})):
    type: str


class Content(TypedDict):
    survey: list[SurveyItem]


class Asset(TypedDict):
    content: Content
    name: str
    uid: str
