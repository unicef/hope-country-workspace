from base64 import b64encode
from collections import UserDict
from collections.abc import Callable, Generator
from enum import StrEnum, auto
from functools import cached_property, reduce
from requests import Response
from typing import Any
from uuid import UUID

from country_workspace.contrib.kobo.api.raw import asset as raw_asset, submission_list as raw_submission_list


class SurveyItemType(StrEnum):
    START = auto()
    END = auto()
    BEGIN_GROUP = auto()
    END_GROUP = auto()
    BEGIN_REPEAT = auto()
    END_REPEAT = auto()



class Raw[T]:
    def __init__(self, raw: T) -> None:
        self._raw = raw


class Question(Raw[raw_asset.SurveyItem]):
    def __init__(self, raw: raw_asset.SurveyItem, in_group: bool, in_roster: bool) -> None:
        super().__init__(raw)
        assert not (in_group and in_roster), "Cannot be both in group and roster"
        self._in_group = in_group
        self._in_roster = in_roster

    def extract_answer(self, in_: raw_submission_list.Submission, out: dict[str, Any]) -> None:
        if self._in_roster:
            roster_key, _ = self.key.split("/")
            roster = out.get(roster_key, [])
            if self.key in in_:
                if roster:
                    roster[0][self.key] = in_.get(self.key)
                else:
                    roster.append({self.key: in_.get(self.key)})
            elif roster_key in in_:
                for i, item in enumerate(in_[roster_key]):
                    if len(roster) < i + 1:
                        roster.append({})
                    roster[i][self.key] = item[self.key]
            out[roster_key] = roster
        else:
            out[self.key] = in_.get(self.key)

    @property
    def key(self) -> str:
        return self._raw["$xpath"]

    @property
    def labels(self) -> list[str]:
        return self._raw["label"]

    def __str__(self) -> str:
        return f"Question: {' '.join(self.labels)}"


InAndOut = tuple[raw_submission_list.Submission, dict[str, Any]]


def _extract_answer(in_and_out: InAndOut, question: Question) -> InAndOut:
    question.extract_answer(*in_and_out)
    return in_and_out


def _download_attachments(data_getter: Callable[[str], Response], raw: raw_submission_list.Submission) -> None:
    for attachment in raw["_attachments"]:
        content = b64encode(data_getter(attachment["download_url"]).content).decode()
        value = f"data:{attachment['mimetype']};base64,{content}"
        key = attachment["question_xpath"]
        if key in raw:
            raw[key] = value
        else:
            parent, key = key.split("/")
            parent, index = parent.split("[")
            index = int(index.rstrip("]")) - 1
            raw[parent][index][f"{parent}/{key}"] = value


class Submission(Raw[raw_submission_list.Submission], UserDict):
    def __init__(self, data_getter: Callable[[str], Response], questions: list[Question], raw: raw_submission_list.Submission) -> None:
        Raw.__init__(self, raw)
        _download_attachments(data_getter, self._raw)
        _, answers = reduce(_extract_answer, questions, (raw, {}))
        UserDict.__init__(self, answers)

    @property
    def uuid(self) -> UUID:
        return UUID(self._raw["_uuid"])


class Asset(Raw[raw_asset.Asset]):
    def __init__(self, raw: raw_asset.Asset, submissions: Callable[[list[Question]], Generator[Submission, None, None]]) -> None:
        super().__init__(raw)
        self._submissions = submissions

    @property
    def uid(self) -> str:
        return self._raw["uid"]

    @property
    def name(self) -> str:
        return self._raw["name"]

    @cached_property
    def questions(self) -> list[Question]:
        in_group = False
        in_roster = False
        questions = []
        for raw_question in self._raw["content"]["survey"]:
            match raw_question["type"]:
                case SurveyItemType.START | SurveyItemType.END:
                    pass
                case SurveyItemType.BEGIN_GROUP:
                    in_group = True
                case SurveyItemType.END_GROUP:
                    in_group = False
                case SurveyItemType.BEGIN_REPEAT:
                    in_roster = True
                case SurveyItemType.END_REPEAT:
                    in_roster = False
                case _:
                    questions.append(Question(raw_question, in_group, in_roster))
        return questions

    @property
    def submissions(self) -> Generator[Submission, None, None]:
        yield from self._submissions(self.questions)

    def __str__(self) -> str:
        return f"Asset: {self.name}"
