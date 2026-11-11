import pytest

from country_workspace.contrib.ona.exceptions import OnaMappingError
from country_workspace.contrib.ona.transformers import (
    filter_ona_sys_fields,
    flatten_ona_data,
    get_nested_value,
    normalize_ona_field_names,
    remove_nested_value,
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


def test_normalize_ona_field_names_keeps_question_names_only():
    source = {
        "deviceid": "c3577347f4584c94",
        "household_location/address_h_c": "3819 Bradley Stream",
        "individual_questions/account_info/bank_account/account__bank__name_i_c": "AIB",
        "meta/instanceID": "uuid:df21d62d",
    }

    assert normalize_ona_field_names(source) == {
        "deviceid": "c3577347f4584c94",
        "address_h_c": "3819 Bradley Stream",
        "account__bank__name_i_c": "AIB",
    }


def test_transform_submission_splits_individual_questions_by_default():
    result = transform_submission_to_records(
        {
            "household_status/size_h_c": 1,
            "individual_questions": [{"individual_questions/individual_details/full_name_i_c": "Kelli Thornton"}],
        },
        master_detail=True,
    )

    assert result["household"]["fields"] == {"household_status/size_h_c": 1}
    assert result["individuals"] == [
        {
            "fields": {"individual_questions/individual_details/full_name_i_c": "Kelli Thornton"},
            "raw_data": {"individual_questions/individual_details/full_name_i_c": "Kelli Thornton"},
        }
    ]


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


def test_get_nested_value_returns_none_when_path_is_not_a_mapping():
    assert get_nested_value({"group": "scalar"}, "group/individuals") is None


def test_remove_nested_value_keeps_data_when_path_is_not_a_mapping():
    data = {"group": "scalar", "keep": 1}

    assert remove_nested_value(data, "group/individuals") == data
    assert data == {"group": "scalar", "keep": 1}


def test_transform_submission_uses_empty_individuals_when_group_is_missing():
    result = transform_submission_to_records(
        {"household/name": "Ahmad Household"},
        master_detail=True,
        individuals_key="individuals",
    )

    assert result["individuals"] == []
    assert result["household"]["fields"] == {"household/name": "Ahmad Household"}


def test_transform_submission_wraps_single_individual_mapping():
    result = transform_submission_to_records(
        {"individual_questions": {"name": "Ahmad Ali"}},
        master_detail=True,
    )

    assert result["individuals"] == [
        {
            "fields": {"name": "Ahmad Ali"},
            "raw_data": {"name": "Ahmad Ali"},
        }
    ]


def test_transform_submission_rejects_non_mapping_individual():
    with pytest.raises(OnaMappingError, match="Invalid individual at index 0"):
        transform_submission_to_records(
            {"individual_questions": ["not-a-record"]},
            master_detail=True,
        )


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
