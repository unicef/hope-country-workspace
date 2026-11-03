import json
from typing import Any

import pytest
from pytest_mock import MockerFixture
from testutils.factories import BatchFactory

from country_workspace.contrib.ona.import_processing import import_submission
from country_workspace.models import Batch, FlexFieldFile
from country_workspace.utils.flex_files import PENDING_PREFIX, FlexFileContent, pending_marker

MEMBER = "individual_questions/individual_details"


def without_paths(row: dict[str, Any]) -> dict[str, Any]:
    """Stand-in for a column mapping: keep the question names, drop repeat groups."""
    return {key.split("/")[-1]: value for key, value in row.items() if not isinstance(value, list)}


@pytest.fixture
def batch(mocker: MockerFixture) -> Batch:
    for name in ("build_household_processor", "build_individual_processor"):
        mocker.patch(f"country_workspace.contrib.ona.import_processing.{name}", return_value=without_paths)
    return BatchFactory()


@pytest.fixture
def files() -> dict[str, FlexFileContent]:
    return {
        key: FlexFileContent(content=key.encode(), mimetype="image/jpeg", filename=key)
        for key in ("consent.jpg", "photo_0.jpg", "national_id_0.jpg", "photo_1.jpg")
    }


@pytest.fixture
def submission() -> dict[str, Any]:
    """A marked household submission: a file of its own, two for one member, one for the other."""
    return {
        "_id": 1,
        "_uuid": "uuid-1",
        "consent/consent_sign_h_c": pending_marker("consent.jpg"),
        "individual_questions": [
            {
                f"{MEMBER}/photo_i_c": pending_marker("photo_0.jpg"),
                f"{MEMBER}/national_id_photo_i_c": pending_marker("national_id_0.jpg"),
            },
            {f"{MEMBER}/photo_i_c": pending_marker("photo_1.jpg")},
        ],
    }


@pytest.mark.django_db
def test_import_submission_stores_the_files_of_each_record(
    batch: Batch, files: dict[str, FlexFileContent], submission: dict[str, Any]
) -> None:
    import_submission(
        batch=batch,
        submission=submission,
        config={
            "batch_name": "ONA batch",
            "validate_after_import": False,
            "form_id": "13591",
            "master_detail": True,
            "individuals_key": "individual_questions",
        },
        files=files,
    )

    household = batch.household_set.get()
    first, second = batch.individual_set.order_by("originating_id")
    stored = {
        (flex_file.object_id, flex_file.field_name): flex_file
        for flex_file in FlexFieldFile.objects.with_content().filter(object_id__in=[household.pk, first.pk, second.pk])
    }
    assert set(stored) == {
        (household.pk, "consent_sign_h_c"),
        (first.pk, "photo_i_c"),
        (first.pk, "national_id_photo_i_c"),
        (second.pk, "photo_i_c"),
    }
    assert stored[(first.pk, "national_id_photo_i_c")].content_bytes == b"national_id_0.jpg"
    assert first.flex_fields["photo_i_c"] == stored[(first.pk, "photo_i_c")].reference
    assert first.raw_data[f"{MEMBER}/photo_i_c"] == first.flex_fields["photo_i_c"]
    assert household.flex_fields["consent_sign_h_c"] == stored[(household.pk, "consent_sign_h_c")].reference
    for record in (household, first, second):
        assert PENDING_PREFIX not in json.dumps([record.flex_fields, record.raw_data])


@pytest.mark.django_db
def test_import_submission_resolves_files_of_a_repeat_group_in_people_only_mode(
    batch: Batch, files: dict[str, FlexFileContent], submission: dict[str, Any]
) -> None:
    import_submission(
        batch=batch,
        submission=submission,
        config={"batch_name": "ONA batch", "validate_after_import": False, "form_id": "13591", "master_detail": False},
        files=files,
    )

    individual = batch.individual_set.get()
    stored = {
        flex_file.reference: flex_file
        for flex_file in FlexFieldFile.objects.with_content().filter(
            object_id=individual.pk, content_type__model="individual"
        )
    }
    first, second = individual.raw_data["individual_questions"]
    assert {
        name: (stored[reference].field_name, stored[reference].content_bytes)
        for name, reference in {
            "consent": individual.raw_data["consent/consent_sign_h_c"],
            "photo_0": first[f"{MEMBER}/photo_i_c"],
            "national_id_0": first[f"{MEMBER}/national_id_photo_i_c"],
            "photo_1": second[f"{MEMBER}/photo_i_c"],
        }.items()
    } == {
        "consent": ("consent_sign_h_c", b"consent.jpg"),
        "photo_0": (f"{MEMBER}/photo_i_c", b"photo_0.jpg"),
        "national_id_0": (f"{MEMBER}/national_id_photo_i_c", b"national_id_0.jpg"),
        "photo_1": (f"{MEMBER}/photo_i_c", b"photo_1.jpg"),
    }
    assert len(stored) == 4
    assert individual.flex_fields["consent_sign_h_c"] == individual.raw_data["consent/consent_sign_h_c"]
    assert PENDING_PREFIX not in json.dumps([individual.flex_fields, individual.raw_data])
