from typing import TypedDict


class Question(TypedDict("Question", {"$autoname": str})):
    label: list[str]


class Content(TypedDict):
    survey: list[Question]


class Asset(TypedDict):
    content: Content
    name: str
    uid: str
