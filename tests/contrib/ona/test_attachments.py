from collections.abc import Callable
from typing import Any

import pytest
from hope_flex_fields.references import DEFAULT_MIMETYPE

from country_workspace.contrib.ona.attachments import download_attachments, get_attachment_name
from country_workspace.contrib.ona.exceptions import (
    OnaApiError,
    OnaAttachmentTooLargeError,
    OnaAuthenticationError,
    OnaNotFoundError,
)
from country_workspace.utils.flex_files import pending_marker

PHOTO = b"\xff\xd8\xffphoto"
FILES_PATH = "/api/v1/files"


def attachment(attachment_id: int, name: str, **extra: Any) -> dict[str, Any]:
    """An `_attachments` entry shaped like the ones returned by INFORM."""
    return {
        "id": attachment_id,
        "name": name,
        "filename": f"user/attachments/13591_form/{name}",
        "mimetype": "image/jpeg",
        "download_url": f"{FILES_PATH}/{attachment_id}?filename=user/attachments/13591_form/{name}",
        **extra,
    }


@pytest.fixture
def downloads() -> list[str]:
    """URLs the stub download was asked for."""
    return []


@pytest.fixture
def download(downloads: list[str]) -> Callable[[str], bytes]:
    def stub(url: str) -> bytes:
        downloads.append(url)
        return PHOTO

    return stub


@pytest.fixture
def household_submission() -> dict[str, Any]:
    """A household answering a file question itself and two in each member row."""
    return {
        "_id": 1,
        "consent/consent_sign_h_c": "consent_1.jpg",
        "individual_questions": [
            {
                "individual_questions/individual_details/photo_i_c": "photo_1_0.jpg",
                "individual_questions/identification/national_id_photo_i_c": "national_id_1_0.jpg",
                "individual_questions/individual_details/full_name_i_c": "John Taylor",
            },
            {
                "individual_questions/individual_details/photo_i_c": "photo_1_1.jpg",
                "individual_questions/individual_details/full_name_i_c": "Jane Taylor",
            },
        ],
        "_attachments": [
            attachment(10, "consent_1.jpg"),
            attachment(11, "photo_1_0.jpg"),
            attachment(12, "national_id_1_0.jpg"),
            attachment(13, "photo_1_1.jpg"),
        ],
    }


def test_download_attachments_marks_every_answer_of_a_household(
    household_submission: dict[str, Any], download: Callable[[str], bytes], downloads: list[str]
) -> None:
    marked, files = download_attachments(download, household_submission)

    assert marked["consent/consent_sign_h_c"] == pending_marker("consent_1.jpg")
    first, second = marked["individual_questions"]
    assert first["individual_questions/individual_details/photo_i_c"] == pending_marker("photo_1_0.jpg")
    assert first["individual_questions/identification/national_id_photo_i_c"] == pending_marker("national_id_1_0.jpg")
    assert first["individual_questions/individual_details/full_name_i_c"] == "John Taylor"
    assert second["individual_questions/individual_details/photo_i_c"] == pending_marker("photo_1_1.jpg")
    assert set(files) == {"consent_1.jpg", "photo_1_0.jpg", "national_id_1_0.jpg", "photo_1_1.jpg"}
    assert files["photo_1_0.jpg"].content == PHOTO
    assert files["photo_1_0.jpg"].mimetype == "image/jpeg"
    assert files["photo_1_0.jpg"].filename == "photo_1_0.jpg"
    assert len(downloads) == 4


def test_download_attachments_leaves_system_fields_and_the_source_untouched(
    household_submission: dict[str, Any], download: Callable[[str], bytes]
) -> None:
    marked, _files = download_attachments(download, household_submission)

    assert marked["_attachments"] == household_submission["_attachments"]
    assert household_submission["consent/consent_sign_h_c"] == "consent_1.jpg"


def test_download_attachments_downloads_a_repeated_answer_once(
    download: Callable[[str], bytes], downloads: list[str]
) -> None:
    submission = {
        "photo": "photo.jpg",
        "group": {"photo_copy": "photo.jpg"},
        "_attachments": [attachment(1, "photo.jpg")],
    }

    marked, files = download_attachments(download, submission)

    assert marked["photo"] == marked["group"]["photo_copy"] == pending_marker("photo.jpg")
    assert list(files) == ["photo.jpg"]
    assert downloads == [f"{FILES_PATH}/1?filename=user/attachments/13591_form/photo.jpg"]


def test_download_attachments_skips_an_unanswered_attachment(
    download: Callable[[str], bytes], downloads: list[str]
) -> None:
    submission = {"photo": "", "_attachments": [attachment(1, "stale.jpg")]}

    marked, files = download_attachments(download, submission)

    assert marked == submission
    assert files == {}
    assert downloads == []


def test_download_attachments_skips_an_attachment_without_download_url(
    download: Callable[[str], bytes], downloads: list[str]
) -> None:
    submission = {"photo": "photo.jpg", "_attachments": [attachment(1, "photo.jpg", download_url="")]}

    marked, files = download_attachments(download, submission)

    assert marked["photo"] == "photo.jpg"
    assert files == {}
    assert downloads == []


@pytest.mark.parametrize("submission", [{"_id": 1, "photo": "photo.jpg"}, {"photo": "photo.jpg", "_attachments": None}])
def test_download_attachments_without_attachments(
    submission: dict[str, Any], download: Callable[[str], bytes], downloads: list[str]
) -> None:
    assert download_attachments(download, submission) == (submission, {})
    assert downloads == []


def test_download_attachments_defaults_the_mimetype(download: Callable[[str], bytes]) -> None:
    submission = {"photo": "photo.jpg", "_attachments": [attachment(1, "photo.jpg", mimetype=None)]}

    _marked, files = download_attachments(download, submission)

    assert files["photo.jpg"].mimetype == DEFAULT_MIMETYPE


@pytest.mark.parametrize(
    "error", [OnaNotFoundError("gone"), OnaAttachmentTooLargeError("too large")], ids=["missing", "too_large"]
)
def test_download_attachments_empties_the_answers_of_a_skipped_attachment(
    household_submission: dict[str, Any], downloads: list[str], error: Exception
) -> None:
    def download(url: str) -> bytes:
        downloads.append(url)
        if "/11?" in url:
            raise error
        return PHOTO

    marked, files = download_attachments(download, household_submission)

    first, second = marked["individual_questions"]
    assert first["individual_questions/individual_details/photo_i_c"] == ""
    assert first["individual_questions/identification/national_id_photo_i_c"] == pending_marker("national_id_1_0.jpg")
    assert second["individual_questions/individual_details/photo_i_c"] == pending_marker("photo_1_1.jpg")
    assert set(files) == {"consent_1.jpg", "national_id_1_0.jpg", "photo_1_1.jpg"}
    assert len(downloads) == 4


def test_download_attachments_tries_a_skipped_attachment_once(downloads: list[str]) -> None:
    def download(url: str) -> bytes:
        downloads.append(url)
        raise OnaNotFoundError("gone")

    submission = {"photo": "photo.jpg", "copy": "photo.jpg", "_attachments": [attachment(1, "photo.jpg")]}

    marked, files = download_attachments(download, submission)

    assert marked["photo"] == marked["copy"] == ""
    assert files == {}
    assert len(downloads) == 1


@pytest.mark.parametrize("error", [OnaAuthenticationError("denied"), OnaApiError("server error")])
def test_download_attachments_propagates_other_errors(household_submission: dict[str, Any], error: Exception) -> None:
    def download(url: str) -> bytes:
        raise error

    with pytest.raises(type(error)):
        download_attachments(download, household_submission)


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"name": "photo.jpg", "filename": "user/attachments/form/other.jpg"}, "photo.jpg"),
        ({"filename": "user/attachments/form/photo.jpg"}, "photo.jpg"),
        ({}, ""),
    ],
)
def test_get_attachment_name_falls_back_to_the_filename(entry: dict[str, Any], expected: str) -> None:
    assert get_attachment_name(entry) == expected
