from base64 import b64encode

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from hope_flex_fields.references import DEFAULT_MIMETYPE, flex_file_src
from pytest_django import DjangoAssertNumQueries

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models import Individual, RdpOperationUnit
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.utils.flex_files import (
    FlexFileContent,
    as_data_uri,
    attach_flex_files,
    flex_file_content,
    materialize_pending_files,
    pending_marker,
    prefetch_flex_files,
    resolve_flex_file,
    resolve_flex_files,
    write_flex_file,
)
from testutils.factories import OcrRdpOperationUnitFactory

LEGACY_DATA_URI = "data:image/png;base64,bGVnYWN5"


@pytest.fixture
def ocr_unit_with_photo(record_with_photo: Individual) -> RdpOperationUnit:
    return OcrRdpOperationUnitFactory(individual=record_with_photo, operation__rdp__program=record_with_photo.program)


@pytest.mark.django_db
def test_write_flex_file_stores_content_owned_by_the_record(record: Individual, photo_content: FlexFileContent) -> None:
    reference = write_flex_file(record, "photo", photo_content.content, photo_content.mimetype, photo_content.filename)

    flex_file = FlexFieldFile.objects.with_content().get(pk=FlexFieldFile.parse_reference(reference))
    assert flex_file.content_bytes == photo_content.content
    assert flex_file.mimetype == photo_content.mimetype
    assert flex_file.size == len(photo_content.content)
    assert flex_file.original_filename == photo_content.filename
    assert flex_file.object_id == record.pk
    assert flex_file.content_type == ContentType.objects.get_for_model(Individual)


@pytest.mark.django_db
def test_write_flex_file_reuses_the_row_of_identical_content(
    record: Individual, photo_content: FlexFileContent
) -> None:
    first = write_flex_file(record, "photo", photo_content.content, photo_content.mimetype)
    same_again = write_flex_file(record, "photo", photo_content.content, photo_content.mimetype)
    replacement = write_flex_file(record, "photo", b"\x89PNG\r\n\x1a\nanother", photo_content.mimetype)

    assert same_again == first
    assert replacement != first
    assert record.flex_field_files.filter(field_name="photo").count() == 2
    resolved = resolve_flex_files(record, {"photo": first})
    assert resolved["photo"] == "data:image/png;base64,%s" % b64encode(photo_content.content).decode()


@pytest.mark.django_db
def test_write_flex_file_keeps_identical_content_under_another_name_apart(
    record: Individual, photo_content: FlexFileContent
) -> None:
    first = write_flex_file(record, "file", photo_content.content, photo_content.mimetype, "front.png")
    same_name = write_flex_file(record, "file", photo_content.content, photo_content.mimetype, "front.png")
    other_name = write_flex_file(record, "file", photo_content.content, photo_content.mimetype, "back.png")

    assert same_name == first
    assert other_name != first
    assert FlexFieldFile.objects.get(pk=FlexFieldFile.parse_reference(other_name)).original_filename == "back.png"


@pytest.mark.django_db
@pytest.mark.parametrize(("update_raw_data", "save"), [(True, True), (False, True), (True, False)])
def test_attach_flex_files_updates_the_requested_payloads(
    record: Individual, photo_content: FlexFileContent, update_raw_data: bool, save: bool
) -> None:
    flex_fields = dict(record.flex_fields)
    raw_data = dict(record.raw_data)

    references = attach_flex_files(record, {"photo": photo_content}, update_raw_data=update_raw_data, save=save)

    assert references == {"photo": record.flex_field_files.get().reference}
    assert record.flex_fields == {**flex_fields, **references}
    assert record.raw_data == ({**raw_data, **references} if update_raw_data else raw_data)
    record.refresh_from_db()
    assert record.flex_fields == ({**flex_fields, **references} if save else flex_fields)
    assert record.raw_data == ({**raw_data, **references} if save and update_raw_data else raw_data)


@pytest.mark.django_db
def test_attach_flex_files_with_no_files_changes_nothing(record: Individual) -> None:
    flex_fields_before = dict(record.flex_fields)

    references = attach_flex_files(record, {})

    assert references == {}
    record.refresh_from_db()
    assert record.flex_fields == flex_fields_before
    assert not record.flex_field_files.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("save", [True, False])
def test_materialize_pending_files_replaces_every_marker_of_one_file(
    record_with_pending_photo: Individual, photo_content: FlexFileContent, save: bool
) -> None:
    references = materialize_pending_files(record_with_pending_photo, {"img-1": photo_content}, save=save)

    reference = record_with_pending_photo.flex_fields["photo"]
    assert references == {"photo": reference}
    assert FlexFieldFile.is_reference(reference)
    assert record_with_pending_photo.raw_data["beneficiary_photo"] == reference
    assert record_with_pending_photo.flex_field_files.count() == 1
    record_with_pending_photo.refresh_from_db()
    expected = reference if save else pending_marker("img-1")
    assert record_with_pending_photo.flex_fields["photo"] == expected
    assert record_with_pending_photo.raw_data["beneficiary_photo"] == expected


@pytest.mark.django_db
def test_materialize_pending_files_with_no_files_changes_nothing(record_with_pending_photo: Individual) -> None:
    markers_before = dict(record_with_pending_photo.flex_fields)

    references = materialize_pending_files(record_with_pending_photo, {})

    assert references == {}
    record_with_pending_photo.refresh_from_db()
    assert record_with_pending_photo.flex_fields == markers_before
    assert not record_with_pending_photo.flex_field_files.exists()


@pytest.mark.django_db
def test_materialize_pending_files_blanks_a_marker_whose_content_is_missing(
    record_with_pending_photo: Individual, photo_content: FlexFileContent
) -> None:
    materialize_pending_files(record_with_pending_photo, {"another-key": photo_content})

    record_with_pending_photo.refresh_from_db()
    assert record_with_pending_photo.flex_fields["photo"] == ""
    assert record_with_pending_photo.raw_data["beneficiary_photo"] == ""
    assert not record_with_pending_photo.flex_field_files.exists()


@pytest.mark.django_db
def test_materialize_pending_files_resolves_nested_markers(record: Individual, photo_content: FlexFileContent) -> None:
    document = FlexFileContent(content=b"%PDF-1.7 document", mimetype="application/pdf", filename="document.pdf")
    record.flex_fields = {**record.flex_fields, "photo": pending_marker("img-1")}
    record.raw_data = {
        **record.raw_data,
        "household": {"photo": pending_marker("img-1"), "name": "Taylor"},
        "members": [{"members/document": pending_marker("doc-1"), "members/name": "John"}, {"members/name": "Jane"}],
    }
    record.save(update_fields=["flex_fields", "raw_data"])

    materialize_pending_files(record, {"img-1": photo_content, "doc-1": document})

    record.refresh_from_db()
    photo = record.flex_fields["photo"]
    assert record.raw_data["household"] == {"photo": photo, "name": "Taylor"}
    first, second = record.raw_data["members"]
    assert FlexFieldFile.is_reference(first["members/document"])
    assert first["members/name"] == "John"
    assert second == {"members/name": "Jane"}
    assert dict(record.flex_field_files.values_list("field_name", "mimetype")) == {
        "photo": photo_content.mimetype,
        "members/document": document.mimetype,
    }


@pytest.mark.django_db
def test_materialize_pending_files_blanks_a_nested_marker_whose_content_is_missing(
    record: Individual, photo_content: FlexFileContent
) -> None:
    record.raw_data = {**record.raw_data, "members": [{"members/photo": pending_marker("missing")}]}
    record.save(update_fields=["raw_data"])

    materialize_pending_files(record, {"img-1": photo_content})

    record.refresh_from_db()
    assert record.raw_data["members"] == [{"members/photo": ""}]
    assert not record.flex_field_files.exists()


@pytest.mark.django_db
def test_materialize_pending_files_keeps_nested_values_without_markers(
    record: Individual, photo_content: FlexFileContent
) -> None:
    nested = {"members": [{"members/name": "John", "members/age": 35}], "group": {"items": [1, 2]}}
    record.raw_data = {**record.raw_data, **nested}
    record.save(update_fields=["raw_data"])

    assert materialize_pending_files(record, {"img-1": photo_content}) == {}

    record.refresh_from_db()
    assert record.raw_data == {"individual_id": "I-1", **nested}
    assert not record.flex_field_files.exists()


@pytest.mark.django_db
def test_resolve_flex_files_expands_references_and_keeps_other_values(
    record_with_photo: Individual, photo_content: FlexFileContent
) -> None:
    reference = record_with_photo.flex_fields["photo"]
    payload = {**record_with_photo.flex_fields, "consent_sign": LEGACY_DATA_URI}
    resolved = resolve_flex_files(record_with_photo, payload)

    assert resolved["photo"] == "data:image/png;base64,%s" % b64encode(photo_content.content).decode()
    assert resolved["consent_sign"] == LEGACY_DATA_URI
    assert resolved["individual_id"] == "I-1"
    assert payload["photo"] == record_with_photo.flex_fields["photo"] == reference
    assert resolve_flex_file(record_with_photo, "photo") == resolved["photo"]
    assert resolve_flex_file(record_with_photo, "missing") is None


@pytest.mark.django_db
@pytest.mark.parametrize("prefetched", [False, True])
def test_resolve_flex_files_raises_on_a_reference_the_record_does_not_own(
    record: Individual, foreign_photo_reference: str, prefetched: bool
) -> None:
    if prefetched:
        record = prefetch_flex_files(Individual.objects.filter(pk=record.pk)).get()

    with pytest.raises(MissingFlexFileError):
        resolve_flex_files(record, {"photo": foreign_photo_reference})


@pytest.mark.django_db
def test_prefetch_flex_files_resolves_without_further_queries(
    record_with_photo: Individual, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    prefetched = prefetch_flex_files(Individual.objects.filter(pk=record_with_photo.pk)).get()

    with django_assert_num_queries(0):
        resolved = resolve_flex_files(prefetched)

    assert resolved["photo"].startswith("data:image/png;base64,")


@pytest.mark.django_db
def test_prefetch_flex_files_with_prefix_resolves_without_further_queries(
    ocr_unit_with_photo: RdpOperationUnit, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    queryset = RdpOperationUnit.objects.filter(pk=ocr_unit_with_photo.pk).select_related("individual")
    prefetched = prefetch_flex_files(queryset, prefix="individual").get()

    with django_assert_num_queries(0):
        resolved = resolve_flex_files(prefetched.individual)

    assert resolved["photo"].startswith("data:image/png;base64,")


@pytest.mark.django_db
def test_prefetch_flex_files_without_content_reads_bytes_only_on_demand(
    record_with_photo: Individual, photo_content: FlexFileContent, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    prefetched = prefetch_flex_files(Individual.objects.filter(pk=record_with_photo.pk), with_content=False).get()
    [flex_file] = prefetched.flex_field_files.all()

    with django_assert_num_queries(1):
        assert flex_file_content(flex_file) == photo_content.content
    assert "content" in flex_file.get_deferred_fields()


@pytest.mark.django_db
def test_as_data_uri_falls_back_to_the_default_mimetype_when_missing(
    record: Individual, photo_content: FlexFileContent
) -> None:
    """A row saved without a mimetype (write_flex_file always fills one in) still renders."""
    flex_file = FlexFieldFile.objects.create(
        content_type=ContentType.objects.get_for_model(Individual),
        object_id=record.pk,
        field_name="photo",
        content=photo_content.content,
        mimetype="",
        size=len(photo_content.content),
        checksum="deadbeef",
    )

    assert as_data_uri(flex_file) == "data:%s;base64,%s" % (DEFAULT_MIMETYPE, b64encode(photo_content.content).decode())


@pytest.mark.django_db
def test_flex_file_src_links_a_reference_to_the_image_view(record_with_photo: Individual) -> None:
    reference = record_with_photo.flex_fields["photo"]

    assert flex_file_src(reference) == reverse("workspace:flex_file", args=[FlexFieldFile.parse_reference(reference)])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(LEGACY_DATA_URI, LEGACY_DATA_URI, id="legacy-data-uri"),
        pytest.param("flexfile:not-a-uuid", "", id="malformed-reference"),
        pytest.param("plain value", "", id="plain-value"),
        pytest.param("", "", id="empty"),
        pytest.param(None, "", id="none"),
    ],
)
def test_flex_file_src_of_non_reference_values(value: str | None, expected: str) -> None:
    assert flex_file_src(value) == expected
