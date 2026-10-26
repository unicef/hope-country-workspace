import pytest

from country_workspace.models import Individual
from country_workspace.utils.flex_files import FlexFileContent, pending_marker, write_flex_file
from testutils.factories import IndividualFactory


@pytest.fixture
def collector():
    return IndividualFactory(flex_fields={"individual_id": "C-1"})


@pytest.fixture
def beneficiary(collector):
    return IndividualFactory(
        flex_fields={"individual_id": "B-1", "collector_id": "C-1"},
        household=collector.household,
    )


@pytest.fixture
def collector_links_qs(beneficiary, collector):
    return Individual.objects.filter(pk__in=[beneficiary.pk, collector.pk])


@pytest.fixture
def beneficiary_with_unknown_ref(collector):
    return IndividualFactory(
        flex_fields={"index_id": 100, "collector_id": "missing-ref"},
        household=collector.household,
    )


@pytest.fixture
def beneficiary_with_extra_fields(collector):
    return IndividualFactory(
        flex_fields={"individual_id": "B-1", "collector_id": "C-1", "name": "John", "photo": "base64data"},
        household=collector.household,
    )


@pytest.fixture
def beneficiary_with_resolved_collector(collector):
    collector.flex_fields["index_id"] = str(collector.pk)
    collector.save(update_fields=["flex_fields"])
    return IndividualFactory(
        flex_fields={"individual_id": "B-1", "collector_id": str(collector.pk)},
        household=collector.household,
    )


@pytest.fixture
def photo_content():
    return FlexFileContent(content=b"\x89PNG\r\n\x1a\nphoto", mimetype="image/png", filename="photo.png")


@pytest.fixture
def record():
    """An individual whose photo field is still empty."""
    return IndividualFactory(flex_fields={"individual_id": "I-1", "photo": ""}, raw_data={"individual_id": "I-1"})


@pytest.fixture
def record_with_photo(record, photo_content):
    """An individual whose photo field holds the reference of a written file."""
    record.flex_fields = {
        **record.flex_fields,
        "photo": write_flex_file(
            record, "photo", photo_content.content, photo_content.mimetype, photo_content.filename
        ),
    }
    record.save(update_fields=["flex_fields"])
    return record


@pytest.fixture
def record_with_pending_photo(record):
    """An individual carrying the same pending marker in `flex_fields` and `raw_data`.

    A mapped file column is stored under its flex field name and under its
    source column name, so both have to end up on the same file.
    """
    record.flex_fields = {**record.flex_fields, "photo": pending_marker("img-1")}
    record.raw_data = {**record.raw_data, "beneficiary_photo": pending_marker("img-1")}
    record.save(update_fields=["flex_fields", "raw_data"])
    return record


@pytest.fixture
def foreign_photo_reference(photo_content):
    """The reference of a file owned by another individual."""
    other = IndividualFactory(flex_fields={"individual_id": "I-2"})
    return write_flex_file(other, "photo", photo_content.content, photo_content.mimetype)
