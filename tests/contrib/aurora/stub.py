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
    "no_results": {
        "results": [],
    },
    "two_results": {
        "results": [
            {
                "pk": 101,
                "fields": {
                    "individual-details": [
                        {
                            "given_name_i_c": "Alice",
                            "family_name_i_c": "Green",
                            "gender_i_c": "female",
                            "birth_date_i_c": "1990-05-12",
                        }
                    ],
                },
                "remote_ip": "198.51.100.10",
                "timestamp": "2025-10-17T14:49:13.554246Z",
            },
            {
                "pk": 102,
                "fields": {
                    "individual-details": [
                        {
                            "given_name_i_c": "Bruno",
                            "family_name_i_c": "Lopez",
                            "gender_i_c": "male",
                            "birth_date_i_c": "1987-03-01",
                        }
                    ],
                },
                "remote_ip": "198.51.100.11",
                "timestamp": "2025-10-17T15:01:02.000000Z",
            },
        ],
    },
    "invalid_pk": {
        "results": [
            {
                "pk": None,
                "fields": {
                    "individual-details": [
                        {
                            "given_name_i_c": "Charlie",
                            "family_name_i_c": "Nguyen",
                            "gender_i_c": "other",
                            "birth_date_i_c": "2000-01-01",
                        }
                    ],
                },
                "remote_ip": "198.51.100.12",
                "timestamp": "2025-10-17T15:30:00.000000Z",
            },
        ],
    },
}
