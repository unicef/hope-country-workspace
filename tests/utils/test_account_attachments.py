import pytest
from django.core.exceptions import ValidationError

from country_workspace.contrib.hope.account_attachments import AccountAttachmentsField
from country_workspace.contrib.hope.constants import ACCOUNT_ATTACHMENT_LIMIT
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.utils.account_attachments import attachment_question_index, attachment_title
from country_workspace.utils.flex_files import FlexFileContent, materialize_pending_files, pending_marker
from testutils.factories import CountryIndividualFactory

REFERENCE = "flexfile:00000000-0000-0000-0000-000000000001"
OTHER_REFERENCE = "flexfile:00000000-0000-0000-0000-000000000002"


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [("attachment_1", 1), ("attachment_10", 10), ("attachment", None), ("attachment_x", None), ("number", None)],
)
def test_attachment_question_index(field_name: str, expected: int | None) -> None:
    assert attachment_question_index(field_name) == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("1770915139616.jpg", "1770915139616.jpg"),
        ("attachments/1770915139616.jpg", "1770915139616.jpg"),
        ("user/attachments/abc/def/contract.pdf", "contract.pdf"),
        ("C:\\scans\\contract.pdf", "contract.pdf"),
        ("", ""),
        (None, ""),
    ],
)
def test_attachment_title_drops_directories(filename: str | None, expected: str) -> None:
    assert attachment_title(filename) == expected


def test_materialize_pending_files_keeps_the_file_name_on_the_stored_file() -> None:
    individual = CountryIndividualFactory(household=None, flex_fields={}, raw_data={})
    marker_1, marker_2 = pending_marker("q1"), pending_marker("q2")
    individual.flex_fields = {"bank_attachments": [{"file": marker_1}, {"file": marker_2, "title": "Kept"}]}
    individual.raw_data = {"account__bank__attachment_1": marker_1, "account__bank__attachment_2": marker_2}
    files = {
        "q1": FlexFileContent(content=b"one", mimetype="image/jpeg", filename="1770915139616.jpg"),
        "q2": FlexFileContent(content=b"two", mimetype="application/pdf", filename="contract.pdf"),
    }

    materialize_pending_files(individual, files)

    individual.refresh_from_db()
    first = individual.raw_data["account__bank__attachment_1"]
    second = individual.raw_data["account__bank__attachment_2"]
    assert individual.flex_fields["bank_attachments"] == [{"file": first}, {"file": second, "title": "Kept"}]
    stored = FlexFieldFile.objects.with_content().get(pk=FlexFieldFile.parse_reference(first))
    assert (stored.content_bytes, stored.original_filename) == (b"one", "1770915139616.jpg")


def test_materialize_pending_files_keeps_the_name_of_each_copy_of_the_same_file() -> None:
    individual = CountryIndividualFactory(household=None, flex_fields={}, raw_data={})
    individual.flex_fields = {"bank_attachments": [{"file": pending_marker("q1")}, {"file": pending_marker("q2")}]}
    files = {
        "q1": FlexFileContent(content=b"scan", mimetype="image/jpeg", filename="front.jpg"),
        "q2": FlexFileContent(content=b"scan", mimetype="image/jpeg", filename="back.jpg"),
    }

    materialize_pending_files(individual, files)

    references = [item["file"] for item in individual.flex_fields["bank_attachments"]]
    names = [FlexFieldFile.objects.get(pk=FlexFieldFile.parse_reference(ref)).original_filename for ref in references]
    assert names == ["front.jpg", "back.jpg"]


class TestAccountAttachmentsField:
    field = AccountAttachmentsField(required=False)

    @pytest.mark.parametrize("value", [None, "", [], "[]", [{"file": ""}, {"title": "orphan"}]])
    def test_empty_values_clean_to_none(self, value: object) -> None:
        assert self.field.clean(value) is None

    def test_normalizes_items(self) -> None:
        value = [{"file": REFERENCE}, {"file": OTHER_REFERENCE, "title": "Contract"}]
        assert self.field.clean(value) == [
            {"file": REFERENCE, "title": ""},
            {"file": OTHER_REFERENCE, "title": "Contract"},
        ]

    def test_accepts_json_text(self) -> None:
        assert self.field.clean(f'[{{"file": "{REFERENCE}"}}]') == [{"file": REFERENCE, "title": ""}]

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ({"file": REFERENCE}, "not_a_list"),
            ([REFERENCE], "invalid_item"),
            ([{"file": REFERENCE, "extra": 1}], "invalid_item"),
            ([{"file": "1770915139616.jpg"}], "not_stored"),
            ([{"file": "data:image/png;base64,AAAA"}], "not_stored"),
            ([{"file": REFERENCE, "title": "x" * 256}], "invalid_title"),
            ([{"file": REFERENCE}] * (ACCOUNT_ATTACHMENT_LIMIT + 1), "too_many"),
        ],
    )
    def test_rejects_invalid_values(self, value: object, code: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            self.field.clean(value)
        assert exc_info.value.code == code
