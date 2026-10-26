import pytest

from country_workspace.contrib.ona.exceptions import OnaMappingError
from country_workspace.contrib.ona.transformers import (
    filter_ona_sys_fields,
    flatten_ona_data,
    get_nested_value,
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


def test_flatten_ona_data_flattens_nested_json():
    source = {
        "household": {
            "name": "Ahmad Household",
            "governorate": "Sana'a",
        }
    }

    assert flatten_ona_data(source) == {
        "household/name": "Ahmad Household",
        "household/governorate": "Sana'a",
    }


def test_filter_ona_sys_fields_removes_metadata():
    source = {
        "_id": 123,
        "_uuid": "abc-123",
        "_submission_time": "2026-06-07T10:00:00",
        "household/name": "Ahmad Household",
    }

    assert filter_ona_sys_fields(source) == {
        "household/name": "Ahmad Household",
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
        individuals_key="individuals",
    )

    assert result["household"] == {
        "fields": {
            "_id": 123,
            "_uuid": "abc-123",
            "_submission_time": "2026-06-07T10:00:00",
            "household/name": "Ahmad Household",
            "household/governorate": "Sana'a",
        },
        "raw_data": {
            "_id": 123,
            "_uuid": "abc-123",
            "_submission_time": "2026-06-07T10:00:00",
            "household/name": "Ahmad Household",
            "household/governorate": "Sana'a",
        },
    }

    assert result["individuals"] == [
        {
            "fields": {
                "name": "Ahmad Ali",
                "age": 35,
                "sex": "Male",
            },
            "raw_data": {
                "name": "Ahmad Ali",
                "age": 35,
                "sex": "Male",
            },
        },
        {
            "fields": {
                "name": "Sara Ahmad",
                "age": 30,
                "sex": "Female",
            },
            "raw_data": {
                "name": "Sara Ahmad",
                "age": 30,
                "sex": "Female",
            },
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
    )

    assert result["household"] is None
    assert result["individuals"] == [
        {
            "fields": submission,
            "raw_data": submission,
        }
    ]


def test_transform_submission_removes_nested_individuals_from_household():
    submission = {
        "_id": 123,
        "household": {"name": "Ahmad Household"},
        "group": {
            "individuals": [
                {"name": "Ahmad Ali"},
            ],
            "other_field": "keep-me",
        },
    }

    result = transform_submission_to_records(
        submission,
        master_detail=True,
        individuals_key="group/individuals",
    )

    assert result["household"]["raw_data"] == {
        "_id": 123,
        "household": {"name": "Ahmad Household"},
        "group": {"other_field": "keep-me"},
    }


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
