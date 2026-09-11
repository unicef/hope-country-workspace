from collections.abc import Callable
from typing import Any

import pytest

from country_workspace.contrib.kobo.api.data.helpers import download_attachments, filter_out_meta_data
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.utils.flex_files import DEFAULT_MIMETYPE, pending_marker

DOWNLOAD_URL = "https://kobo.example.org/attachment/1"
PHOTO = b"\x89PNG\r\n\x1a\nphoto"


class StubResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


@pytest.fixture
def downloads() -> list[str]:
    """URLs the stub data getter was asked for."""
    return []


@pytest.fixture
def data_getter(downloads: list[str]) -> Callable[[str], StubResponse]:
    def getter(url: str) -> StubResponse:
        downloads.append(url)
        return StubResponse(PHOTO)

    return getter


def submission(attachment: dict[str, Any], **answers: Any) -> Submission:
    return Submission({"_id": 1, "_attachments": [attachment], **answers})


@pytest.fixture
def top_level_answer() -> Submission:
    """A submission whose attachment answers a question of its own."""
    return submission(
        {"download_url": DOWNLOAD_URL, "mimetype": "image/png", "question_xpath": "photo"},
        photo="photo.png",
    )


@pytest.fixture
def repeated_group_answer() -> Submission:
    """A submission whose attachment answers a question inside a repeated group."""
    return submission(
        {"download_url": DOWNLOAD_URL, "mimetype": "image/png", "question_xpath": "members[1]/photo"},
        members=[{"members/photo": "photo.png"}],
    )


@pytest.fixture
def attachment_without_mimetype() -> Submission:
    return submission({"download_url": DOWNLOAD_URL, "question_xpath": "photo"}, photo="photo.png")


@pytest.fixture
def attachment_without_xpath() -> Submission:
    return submission({"download_url": DOWNLOAD_URL, "mimetype": "image/png"}, photo="photo.png")


def test_filter_out_meta_data() -> None:
    data = {
        "_key": "_value",
        (key := "key"): "value",
    }
    filtered = filter_out_meta_data(data)
    assert filtered == {key: data[key]}


def test_download_attachments_marks_a_top_level_answer(
    top_level_answer: Submission, data_getter: Callable[[str], StubResponse], downloads: list[str]
) -> None:
    result = download_attachments(data_getter, top_level_answer)

    assert result["photo"] == pending_marker("photo")
    assert result.files["photo"].content == PHOTO
    assert result.files["photo"].mimetype == "image/png"
    assert downloads == [DOWNLOAD_URL]


def test_download_attachments_marks_an_answer_of_a_repeated_group(
    repeated_group_answer: Submission, data_getter: Callable[[str], StubResponse]
) -> None:
    result = download_attachments(data_getter, repeated_group_answer)

    assert result["members"][0]["members/photo"] == pending_marker("members[1]/photo")
    assert result.files["members[1]/photo"].content == PHOTO


def test_download_attachments_defaults_the_mimetype(
    attachment_without_mimetype: Submission, data_getter: Callable[[str], StubResponse]
) -> None:
    result = download_attachments(data_getter, attachment_without_mimetype)

    assert result.files["photo"].mimetype == DEFAULT_MIMETYPE


def test_download_attachments_skips_an_attachment_without_xpath(
    attachment_without_xpath: Submission, data_getter: Callable[[str], StubResponse], downloads: list[str]
) -> None:
    result = download_attachments(data_getter, attachment_without_xpath)

    assert result.files == {}
    assert result["photo"] == "photo.png"
    assert downloads == []
