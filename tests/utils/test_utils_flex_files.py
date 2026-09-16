from base64 import b64encode

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models import Individual
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.utils.flex_files import (
    DEFAULT_MIMETYPE,
    FlexFileContent,
    as_data_uri,
    attach_flex_files,
    flex_file_src,
    materialize_pending_files,
    prefetch_flex_files,
    resolve_flex_files,
    write_flex_file,
)

LEGACY_DATA_URI = "data:image/png;base64,bGVnYWN5"


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


@pytest.mark.django_db
def test_attach_flex_files_references_the_file_in_both_payloads(
    record: Individual, photo_content: FlexFileContent
) -> None:
    references = attach_flex_files(record, {"photo": photo_content})

    record.refresh_from_db()
    assert FlexFieldFile.is_reference(references["photo"])
    assert record.flex_fields["photo"] == references["photo"]
    assert record.raw_data["photo"] == references["photo"]


@pytest.mark.django_db
def test_attach_flex_files_with_no_files_changes_nothing(record: Individual) -> None:
    flex_fields_before = dict(record.flex_fields)

    references = attach_flex_files(record, {})

    assert references == {}
    record.refresh_from_db()
    assert record.flex_fields == flex_fields_before
    assert not record.flex_field_files.exists()


@pytest.mark.django_db
def test_materialize_pending_files_replaces_every_marker_of_one_file(
    record_with_pending_photo: Individual, photo_content: FlexFileContent
) -> None:
    materialize_pending_files(record_with_pending_photo, {"img-1": photo_content})

    record_with_pending_photo.refresh_from_db()
    reference = record_with_pending_photo.flex_fields["photo"]
    assert FlexFieldFile.is_reference(reference)
    assert record_with_pending_photo.raw_data["beneficiary_photo"] == reference
    assert record_with_pending_photo.flex_field_files.count() == 1


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
def test_resolve_flex_files_expands_references_and_keeps_other_values(
    record_with_photo: Individual, photo_content: FlexFileContent
) -> None:
    resolved = resolve_flex_files(
        record_with_photo,
        {**record_with_photo.flex_fields, "consent_sign": LEGACY_DATA_URI},
    )

    assert resolved["photo"] == "data:image/png;base64,%s" % b64encode(photo_content.content).decode()
    assert resolved["consent_sign"] == LEGACY_DATA_URI
    assert resolved["individual_id"] == "I-1"


@pytest.mark.django_db
def test_resolve_flex_files_raises_on_a_reference_the_record_does_not_own(
    record: Individual, foreign_photo_reference: str
) -> None:
    with pytest.raises(MissingFlexFileError):
        resolve_flex_files(record, {"photo": foreign_photo_reference})


@pytest.mark.django_db
def test_prefetch_flex_files_resolves_without_further_queries(
    record_with_photo: Individual, django_assert_num_queries
) -> None:
    prefetched = prefetch_flex_files(Individual.objects.filter(pk=record_with_photo.pk)).get()

    with django_assert_num_queries(0):
        resolved = resolve_flex_files(prefetched)

    assert resolved["photo"].startswith("data:image/png;base64,")


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
