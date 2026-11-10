import pytest
from django.utils.functional import empty
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.constants import ACCOUNT_ATTACHMENT_LIMIT, ACCOUNT_ATTACHMENT_SIZE_LIMIT
from country_workspace.exceptions import BlobStorageError, InvalidAccountAttachmentError, MissingFlexFileError
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.services.hope_blob import sync_account_attachments
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_files import write_flex_file
from testutils.factories import CountryIndividualFactory

pytestmark = pytest.mark.django_db

JPG = b"\xff\xd8\xff\xe0jpeg-bytes"
PDF = b"%PDF-1.7 contract"


@pytest.fixture(autouse=True)
def _reset_hope_storage():
    HOPE_STORAGE._wrapped = empty
    yield
    HOPE_STORAGE._wrapped = empty


@pytest.fixture
def individual():
    individual = CountryIndividualFactory(household=None, flex_fields={"bank_number": "EXAMPLE_ACCOUNT"})
    jpg = write_flex_file(individual, "file", JPG, "image/jpeg", "1770915139616.jpg")
    pdf = write_flex_file(individual, "file", PDF, "application/pdf", "scans/Contract.PDF")
    individual.flex_fields["bank_attachments"] = [{"file": jpg}, {"file": pdf, "title": "Signed contract"}]
    individual.save(update_fields=["flex_fields"])
    return individual


def key_for(individual, reference: str, extension: str) -> str:
    return individual.hope_attachment_key(FlexFieldFile.parse_reference(reference), extension)


def test_uploads_original_bytes_and_returns_storage_keys(individual) -> None:
    jpg, pdf = (item["file"] for item in individual.flex_fields["bank_attachments"])

    result = sync_account_attachments(individual)

    assert result == {
        "bank_attachments": [
            {"file": key_for(individual, jpg, ".jpg"), "title": "1770915139616.jpg"},
            {"file": key_for(individual, pdf, ".pdf"), "title": "Signed contract"},
        ]
    }
    program = individual.program
    for item, content in zip(result["bank_attachments"], (JPG, PDF), strict=True):
        assert item["file"].startswith(f"2024/{individual.country_office.slug}/{program.code}/CW_ind_{individual.pk}_")
        with HOPE_STORAGE.open(item["file"]) as fh:
            assert fh.read() == content


def test_untitled_attachments_are_titled_after_the_file_name_without_directories(individual) -> None:
    individual.flex_fields["bank_attachments"][1].pop("title")

    result = sync_account_attachments(individual)

    assert [item["title"] for item in result["bank_attachments"]] == ["1770915139616.jpg", "Contract.PDF"]


def test_records_without_attachments_touch_nothing(mocker: MockerFixture) -> None:
    storage = mocker.patch("country_workspace.services.hope_blob.HOPE_STORAGE")
    individual = CountryIndividualFactory(household=None, flex_fields={"bank_number": "1"})

    assert sync_account_attachments(individual) == {}
    assert not storage.method_calls


def test_retry_reuses_uploaded_files(individual, mocker: MockerFixture) -> None:
    first = sync_account_attachments(individual)
    save = mocker.spy(HOPE_STORAGE, "save")

    assert sync_account_attachments(individual) == first
    save.assert_not_called()


def test_retry_uploads_only_files_missing_from_storage(individual, mocker: MockerFixture) -> None:
    first = sync_account_attachments(individual)
    HOPE_STORAGE.delete(first["bank_attachments"][1]["file"])
    save = mocker.spy(HOPE_STORAGE, "save")

    assert sync_account_attachments(individual) == first
    assert [call.args[0] for call in save.call_args_list] == [first["bank_attachments"][1]["file"]]


def test_uploaded_files_are_never_deleted(individual, mocker: MockerFixture) -> None:
    first = sync_account_attachments(individual)
    delete = mocker.spy(HOPE_STORAGE, "delete")
    individual.flex_fields["bank_attachments"] = []

    assert sync_account_attachments(individual) == {"bank_attachments": None}
    delete.assert_not_called()
    assert all(HOPE_STORAGE.exists(item["file"]) for item in first["bank_attachments"])


def test_replaced_file_gets_a_new_key_and_keeps_the_old_one(individual) -> None:
    [old, _] = sync_account_attachments(individual)["bank_attachments"]
    replacement = write_flex_file(individual, "file", JPG + b"-v2", "image/jpeg", "1770915139616.jpg")
    individual.flex_fields["bank_attachments"][0]["file"] = replacement

    [new, _] = sync_account_attachments(individual)["bank_attachments"]

    assert new["file"] != old["file"]
    assert HOPE_STORAGE.exists(old["file"])


@pytest.mark.parametrize("reference", ["flexfile:00000000-0000-0000-0000-000000000000", "1770915139616.jpg"])
def test_missing_or_unstored_file_raises(individual, reference: str) -> None:
    individual.flex_fields["bank_attachments"].append({"file": reference})

    with pytest.raises(MissingFlexFileError, match="bank_attachments"):
        sync_account_attachments(individual)


def test_file_of_another_record_raises(individual) -> None:
    stranger = CountryIndividualFactory(household=None)
    foreign = write_flex_file(stranger, "file", PDF, "application/pdf", "secret.pdf")
    individual.flex_fields["bank_attachments"] = [{"file": foreign}]

    with pytest.raises(MissingFlexFileError):
        sync_account_attachments(individual)
    assert not HOPE_STORAGE.exists(key_for(individual, foreign, ".pdf"))


def test_oversized_file_raises(individual) -> None:
    reference = individual.flex_fields["bank_attachments"][0]["file"]
    FlexFieldFile.objects.filter(pk=FlexFieldFile.parse_reference(reference)).update(
        size=ACCOUNT_ATTACHMENT_SIZE_LIMIT + 1
    )

    with pytest.raises(InvalidAccountAttachmentError, match="at most"):
        sync_account_attachments(individual)


def test_too_many_attachments_raise(individual) -> None:
    item = individual.flex_fields["bank_attachments"][0]
    individual.flex_fields["bank_attachments"] = [item] * (ACCOUNT_ATTACHMENT_LIMIT + 1)

    with pytest.raises(InvalidAccountAttachmentError, match=f"at most {ACCOUNT_ATTACHMENT_LIMIT}"):
        sync_account_attachments(individual)


@pytest.mark.parametrize(
    ("filename", "mimetype", "extension"),
    [
        ("scan", "image/png", ".png"),
        ("scan.JPEG", "application/octet-stream", ".jpeg"),
        ("", "application/pdf", ".pdf"),
    ],
)
def test_extension_falls_back_to_the_media_type(individual, filename: str, mimetype: str, extension: str) -> None:
    reference = write_flex_file(individual, "file", b"other", mimetype, filename)
    individual.flex_fields["bank_attachments"] = [{"file": reference}]

    [item] = sync_account_attachments(individual)["bank_attachments"]

    assert item["file"] == key_for(individual, reference, extension)


def test_file_type_hope_does_not_accept_raises(individual) -> None:
    reference = write_flex_file(individual, "file", b"<html>", "text/html", "page.html")
    individual.flex_fields["bank_attachments"] = [{"file": reference}]

    with pytest.raises(InvalidAccountAttachmentError, match="file types HOPE accepts"):
        sync_account_attachments(individual)


def test_storage_failure_is_reported_as_blob_storage_error(individual, mocker: MockerFixture) -> None:
    mocker.patch.object(HOPE_STORAGE, "exists", side_effect=OSError("down"))

    with pytest.raises(BlobStorageError, match="attachment upload failed"):
        sync_account_attachments(individual)
