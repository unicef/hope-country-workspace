from collections import UserDict
from collections.abc import Callable, Generator
from uuid import UUID

from country_workspace.contrib.kobo.raw import asset as raw_asset
from country_workspace.contrib.kobo.raw import submission_list as raw_submission_list


class Raw[T]:
    def __init__(self, raw: T) -> None:
        self._raw = raw


class Question(Raw[raw_asset.Question]):
    @property
    def key(self) -> str:
        return self._raw["$autoname"]

    @property
    def label(self) -> list[str]:
        return self._raw["label"]


class Submission(Raw[raw_submission_list.Submission], UserDict):
    def __init__(self, raw: raw_submission_list.Submission, questions: list[Question]) -> None:
        Raw.__init__(self, raw)
        UserDict.__init__(self, {question.key: raw[question.key] for question in questions})

    @property
    def uuid(self) -> UUID:
        return UUID(self._raw["_uuid"])


class Asset(Raw[raw_asset.Asset]):
    def __init__(self, raw: raw_asset.Asset, submissions: Generator[Callable[[list[Question]], Submission], None, None]) -> None:
        super().__init__(raw)
        self._submissions = submissions

    @property
    def uid(self) -> str:
        return self._raw["uid"]

    @property
    def name(self) -> str:
        return self._raw["name"]

    @property
    def questions(self) -> list[Question]:
        return [Question(raw_question) for raw_question in self._raw["content"]["survey"] if "label" in raw_question]

    @property
    def submissions(self) -> Generator[Submission, None, None]:
        return (submission(self.questions) for submission in self._submissions)
