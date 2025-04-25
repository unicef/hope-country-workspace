from typing import Any, Final

project: Final[dict[str, dict[str, list[dict[str, Any]]]]] = {
    "results": [
        {
            "id": 6,
            "name": "Lanka Project #1",
        },
        {
            "id": 1,
            "name": "Default Project",
        },
    ]
}

registration: Final[dict[str, dict[str, list[dict[str, Any]]]]] = {
    "results": [
        {
            "id": 1,
            "name": "Registration 1",
            "active": True,
            "project": "http://example.com/api/project/1/",
        },
        {
            "id": 2,
            "name": "Registration 2",
            "active": True,
            "project": "invalid_url",
        },
        {
            "id": 3,
            "name": "Registration 3",
            "active": True,
            "project": "http://example.com/api/project/1/",
        },
        {
            "id": 4,
            "name": "Registration 4",
            "active": True,
            "project": "http://example.com/api/project/9999/",
        },
        {
            "id": 1,
            "name": "Registration 5",
            "active": True,
            "project": "http://example.com/api/project/1/",
        },
    ],
    "next": None,
}

imported: Final[dict[str, dict[str, Any]]] = {
    "correct": {
        "page": 1,
        "results": [
            {
                "id": 5,
                "flatten": {
                    "household_0_admin1": "UA01",
                    "individuals_0_relationship": "head",
                    "individuals_0_given_name": "John",
                    "individuals_0_gender": "male",
                    "id": 5,
                },
            },
            {
                "id": 6,
                "flatten": {
                    "household_0_admin1": "UA02",
                    "individuals_0_relationship": "head",
                    "individuals_0_given_name": "Jane",
                    "individuals_0_gender": "female",
                    "individuals_1_relationship": "son_daughter",
                    "individuals_1_given_name": "Tom",
                    "individuals_1_gender": "male",
                    "id": 6,
                },
            },
        ],
    },
    "no_individuals": {
        "page": 1,
        "results": [
            {
                "id": 7,
                "flatten": {
                    "household_0_admin1": "UA03",
                    "id": 7,
                },
            },
        ],
    },
    "multiple_households": {
        "page": 1,
        "results": [
            {
                "id": 8,
                "flatten": {
                    "household_0_admin1": "UA04",
                    "household_1_admin1": "UA05",
                    "individuals_0_relationship": "head",
                    "individuals_0_given_name": "Alice",
                    "individuals_0_gender": "female",
                    "id": 8,
                },
            },
        ],
    },
    "empty_household_data": {
        "page": 1,
        "results": [
            {
                "id": 9,
                "flatten": {
                    "individuals_0_relationship_i_c": "head",
                    "individuals_0_given_name_i_c": "Bob",
                    "individuals_0_gender_i_c": "male",
                    "id": 9,
                },
            },
        ],
    },
    "update_head_name": {
        "page": 1,
        "results": [
            {
                "id": 10,
                "flatten": {
                    "household_0_admin1_h_c": "UA06",
                    "individuals_0_relationship_i_c": "head",
                    "individuals_0_given_name_i_c": "Mike",
                    "individuals_0_gender_i_c": "male",
                    "individuals_0_family_name_i_c": "Doe",
                    "id": 10,
                },
            },
        ],
    },
    "invalid_key": {
        "page": 1,
        "results": [
            {
                "id": 11,
                "flatten": {
                    "individuals_wrong": "value",
                    "household_invalid": "data",
                    "id": 11,
                },
            },
        ],
    },
    "multiple_individuals_if_not_hh": {
        "page": 1,
        "results": [
            {
                "id": 12,
                "flatten": {
                    "individuals_0_relationship": "head",
                    "individuals_0_given_name": "Alice",
                    "individuals_0_gender": "female",
                    "individuals_1_given_name": "Tom",
                    "id": 12,
                },
            },
        ],
    },
    "invalid_record_id": {
        "page": 1,
        "results": [
            {
                "id": 13,
                "flatten": {
                    "individuals_0_given_name": "Tom",
                },
            },
        ],
    },
}
