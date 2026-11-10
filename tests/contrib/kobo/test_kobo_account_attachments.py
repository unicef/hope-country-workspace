from typing import Any

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.api.data.helpers import download_attachments
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.sync import Config, create_household, create_individuals, get_id_generator
from country_workspace.models import Batch, Individual
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.workspaces.admin.batch.reprocessing import reprocess_batch
from testutils.factories import AsyncJobFactory, BatchFactory

pytestmark = pytest.mark.django_db

GROUP = "individual_questions"
DETAILS = f"{GROUP}/individual_details"
CONTENT = {
    "https://kobo.example.org/attachment/1": b"\xff\xd8first",
    "https://kobo.example.org/attachment/2": b"%PDF-second",
    "https://kobo.example.org/attachment/10": b"\x89PNGtenth",
    "https://kobo.example.org/attachment/m1": b"\xff\xd8wallet",
}


class StubResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


def attachment(question: str, filename: str, url: str, mimetype: str) -> dict[str, Any]:
    return {
        "question_xpath": f"{GROUP}[1]/individual_details/{question}",
        "filename": filename,
        "mimetype": mimetype,
        "download_url": url,
    }


@pytest.fixture
def submission() -> Submission:
    raw = {
        "_id": 7,
        GROUP: [
            {
                f"{DETAILS}/full_name": "Jane Doe",
                f"{DETAILS}/account__bank__number": "EXAMPLE_ACCOUNT",
                f"{DETAILS}/account__bank__attachment_10": "tenth.png",
                f"{DETAILS}/account__bank__attachment_2": "second.pdf",
                f"{DETAILS}/account__bank__attachment_1": "1770915139616.jpg",
                f"{DETAILS}/account__mobile__attachment_1": "wallet.jpg",
            }
        ],
        "_attachments": [
            attachment(
                "account__bank__attachment_10",
                "u/attachments/x/tenth.png",
                "https://kobo.example.org/attachment/10",
                "image/png",
            ),
            attachment(
                "account__bank__attachment_2",
                "u/attachments/x/second.pdf",
                "https://kobo.example.org/attachment/2",
                "application/pdf",
            ),
            attachment(
                "account__bank__attachment_1",
                "attachments/1770915139616.jpg",
                "https://kobo.example.org/attachment/1",
                "image/jpeg",
            ),
            attachment("account__mobile__attachment_1", "", "https://kobo.example.org/attachment/m1", "image/jpeg"),
        ],
    }
    return download_attachments(lambda url: StubResponse(CONTENT[url]), Submission(raw))


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": "kobo",
        "project_id": "asset",
        "individual_records_field": GROUP,
        "validate_after_import": False,
    }


@pytest.fixture
def batch() -> Batch:
    return BatchFactory(source=Batch.BatchSource.KOBO)


@pytest.fixture
def imported(batch: Batch, submission: Submission, config: Config) -> Individual:
    household = create_household(batch, submission, config, get_id_generator(), "asset/7")
    [item] = create_individuals(batch, household, submission, config, "asset")
    item.individual.refresh_from_db()
    return item.individual


def stored(reference: str) -> FlexFieldFile:
    return FlexFieldFile.objects.with_content().get(pk=FlexFieldFile.parse_reference(reference))


def test_download_keeps_the_original_file_name(submission: Submission) -> None:
    files = {xpath.rsplit("/", 1)[1]: item.filename for xpath, item in submission.files.items()}

    assert files == {
        "account__bank__attachment_1": "1770915139616.jpg",
        "account__bank__attachment_2": "second.pdf",
        "account__bank__attachment_10": "tenth.png",
        # Kobo gave no file name: the answer of the question is used instead
        "account__mobile__attachment_1": "wallet.jpg",
    }


def test_import_groups_attachments_per_account_in_order(imported: Individual) -> None:
    bank = imported.flex_fields["bank_attachments"]
    mobile = imported.flex_fields["mobile_attachments"]

    assert imported.flex_fields["bank_number"] == "EXAMPLE_ACCOUNT"
    assert "bank_data" not in imported.flex_fields
    assert [(stored(item["file"]).original_filename, stored(item["file"]).content_bytes) for item in bank] == [
        ("1770915139616.jpg", CONTENT["https://kobo.example.org/attachment/1"]),
        ("second.pdf", CONTENT["https://kobo.example.org/attachment/2"]),
        ("tenth.png", CONTENT["https://kobo.example.org/attachment/10"]),
    ]
    assert mobile == [{"file": mobile[0]["file"]}]
    assert stored(mobile[0]["file"]).original_filename == "wallet.jpg"


def test_import_keeps_only_references_in_raw_data(imported: Individual) -> None:
    raw_value = imported.raw_data[f"{DETAILS}/account__bank__attachment_1"]

    assert raw_value == imported.flex_fields["bank_attachments"][0]["file"]
    assert FlexFieldFile.is_reference(raw_value)


def test_reprocessing_preserves_file_references(imported: Individual, batch: Batch, mocker: MockerFixture) -> None:
    expected = {key: imported.flex_fields[key] for key in ("bank_attachments", "mobile_attachments")}
    imported.flex_fields = {"full_name": "edited"}
    imported.save(update_fields=["flex_fields"])
    mocker.patch("country_workspace.workspaces.admin.batch.reprocessing.create_validation_jobs")
    mocker.patch("country_workspace.workspaces.admin.batch.reprocessing.run_batch_postprocessing")
    files_before = FlexFieldFile.objects.count()

    reprocess_batch(AsyncJobFactory(program=batch.program, batch=batch, config={"batch_id": batch.pk}))

    imported.refresh_from_db()
    assert {key: imported.flex_fields[key] for key in expected} == expected
    assert FlexFieldFile.objects.count() == files_before
