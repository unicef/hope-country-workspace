from typing import Any

import pytest
from testutils.factories import BatchFactory

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.contrib.ona.import_processing import import_submission

DETAILS = "individual_questions/individual_details"


@pytest.fixture
def submission() -> dict[str, Any]:
    """A trimmed INFORM household submission, keyed the way the ONA data API returns it."""
    return {
        "_id": 13455118,
        "_uuid": "df21d62d-a215-4746-8be6-8ac26f82675b",
        "_geolocation": [30.420069, 70.747853],
        "meta/instanceID": "uuid:df21d62d-a215-4746-8be6-8ac26f82675b",
        "setup/currency_h_c": "AFN",
        "consent/consent_h_c": "1",
        "household_status/size_h_c": 2,
        "household_status/residence_status_h_c": "host",
        "household_location/address_h_c": "3819 Bradley Stream",
        "household_location/country_h_c": "AFG",
        "individual_questions": [
            {
                f"{DETAILS}/full_name_i_c": "Kelli Thornton",
                f"{DETAILS}/gender_i_c": "female",
                f"{DETAILS}/relationship_i_c": "head",
                f"{DETAILS}/role_i_c": "primary",
            },
            {
                f"{DETAILS}/full_name_i_c": "Pamela Pearson",
                f"{DETAILS}/gender_i_c": "female",
                f"{DETAILS}/relationship_i_c": "granddaugher_grandson",
                f"{DETAILS}/role_i_c": "alternate",
            },
        ],
    }


@pytest.mark.django_db
def test_import_submission_keys_fields_by_question_name(submission: dict[str, Any]) -> None:
    batch = BatchFactory()

    import_submission(
        batch=batch,
        submission=submission,
        config={
            "batch_name": "ONA batch",
            "validate_after_import": False,
            "form_id": "13591",
            "master_detail": True,
        },
    )

    household = batch.household_set.get()
    head, alternate = batch.individual_set.order_by("originating_id")

    assert {
        "currency": "AFN",
        "consent": "1",
        "size": 2,
        "residence_status": "HOST",
        "address": "3819 Bradley Stream",
        "country": "AFG",
    }.items() <= household.flex_fields.items()
    assert not [key for key in household.flex_fields if "/" in key or key in {"instanceid", "individual_questions"}]
    assert household.raw_data["household_location/address_h_c"] == "3819 Bradley Stream"

    assert {
        "full_name": "Kelli Thornton",
        "gender": "FEMALE",
        "relationship": "HEAD",
        "role": "PRIMARY",
    }.items() <= head.flex_fields.items()
    assert not [key for key in head.flex_fields if "/" in key]

    assert household.flex_fields[HOUSEHOLD_ROLE_REF_FIELDS.head_of_household] == head.pk
    assert household.flex_fields[HOUSEHOLD_ROLE_REF_FIELDS.primary_collector] == head.pk
    assert household.flex_fields[HOUSEHOLD_ROLE_REF_FIELDS.alternate_collector] == alternate.pk
