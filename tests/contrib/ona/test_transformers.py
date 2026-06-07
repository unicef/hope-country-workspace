import pytest

from country_workspace.contrib.ona.exceptions import OnaMappingError
from country_workspace.contrib.ona.transformers import (
    get_nested_value,
    map_fields,
    transform_submission_to_records,
)


def test_get_nested_value_supports_flat_ona_keys():
    data = {
        "household/head/name": "Ahmad Ali",
    }

    assert get_nested_value(data, "household/head/name") == "Ahmad Ali"


def test_get_nested_value_supports_nested_json():
    data = {
        "household": {
            "head": {
                "name": "Ahmad Ali",
            }
        }
    }

    assert get_nested_value(data, "household/head/name") == "Ahmad Ali"


def test_map_fields_maps_ona_fields_to_target_fields():
    source = {
        "hh/name": "Ahmad Household",
        "hh/governorate": "Sana'a",
    }

    result = map_fields(
        source,
        {
            "hh/name": "household_name",
            "hh/governorate": "residence_governorate",
        },
    )

    assert result == {
        "household_name": "Ahmad Household",
        "residence_governorate": "Sana'a",
    }


def test_transform_submission_to_records_master_detail():
    submission = {
        "_id": 123,
        "_uuid": "abc-123",
        "_submission_time": "2026-06-07T10:00:00",
        "household/name": "Ahmad Household",
        "household/governorate": "Sana'a",
        "individuals": [
            {
                "name": "Ahmad Ali",
                "age": 35,
                "sex": "Male",
            },
            {
                "name": "Sara Ahmad",
                "age": 30,
                "sex": "Female",
            },
        ],
    }

    result = transform_submission_to_records(
        submission,
        master_detail=True,
        household_field_mapping={
            "household/name": "household_name",
            "household/governorate": "residence_governorate",
        },
        individual_field_mapping={
            "name": "full_name",
            "age": "age",
            "sex": "sex",
        },
        individuals_key="individuals",
    )

    assert result["household"] == {
        "household_name": "Ahmad Household",
        "residence_governorate": "Sana'a",
        "source_submission_id": 123,
        "source_submission_uuid": "abc-123",
        "source_submission_time": "2026-06-07T10:00:00",
    }

    assert result["individuals"] == [
        {
            "full_name": "Ahmad Ali",
            "age": 35,
            "sex": "Male",
            "source_submission_id": 123,
            "source_submission_uuid": "abc-123",
            "source_submission_time": "2026-06-07T10:00:00",
            "source_individual_index": 0,
        },
        {
            "full_name": "Sara Ahmad",
            "age": 30,
            "sex": "Female",
            "source_submission_id": 123,
            "source_submission_uuid": "abc-123",
            "source_submission_time": "2026-06-07T10:00:00",
            "source_individual_index": 1,
        },
    ]


def test_transform_submission_to_records_non_master_detail():
    submission = {
        "_id": 123,
        "_uuid": "abc-123",
        "_submission_time": "2026-06-07T10:00:00",
        "name": "Ahmad Ali",
        "age": 35,
        "sex": "Male",
    }

    result = transform_submission_to_records(
        submission,
        master_detail=False,
        individual_field_mapping={
            "name": "full_name",
            "age": "age",
            "sex": "sex",
        },
    )

    assert result["household"] is None
    assert result["individuals"] == [
        {
            "full_name": "Ahmad Ali",
            "age": 35,
            "sex": "Male",
            "source_submission_id": 123,
            "source_submission_uuid": "abc-123",
            "source_submission_time": "2026-06-07T10:00:00",
        }
    ]


def test_transform_submission_to_records_rejects_invalid_individuals_group():
    submission = {
        "_id": 123,
        "individuals": "wrong-value",
    }

    with pytest.raises(OnaMappingError):
        transform_submission_to_records(
            submission,
            master_detail=True,
            individuals_key="individuals",
        )