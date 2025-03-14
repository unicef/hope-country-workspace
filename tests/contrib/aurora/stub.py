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

imported: Final[dict[str, dict[str, list[dict[str, Any]]]]] = {
    "without_prefix_household": {
        "page": 1,
        "results": [
            {
                "id": 1,
                "flatten": {
                    "counters_rounds": "2",
                    "houshold_0_admin1_h_c": "UA01",
                    "individuals_0_gender_i_c": "male",
                },
            }
        ],
    },
    "without_prefix_individuals": {
        "page": 1,
        "results": [
            {
                "id": 2,
                "flatten": {
                    "counters_rounds": "2",
                    "household_0_admin1_h_c": "UA01",
                    "inividuals_0_gender_i_c": "male",
                },
            }
        ],
    },
    "multiple_households": {
        "page": 1,
        "results": [
            {
                "id": 3,
                "flatten": {
                    "counters_rounds": "2",
                    "household_0_admin1_h_c": "UA01",
                    "household_1_admin1_h_c": "UA01",
                },
            }
        ],
    },
    "without_head": {
        "page": 1,
        "results": [
            {
                "id": 4,
                "flatten": {
                    "counters_rounds": "2",
                    "household_0_admin1_h_c": "UA01",
                    "individuals_0_id_type": "tax_id",
                    "individuals_0_tax_id_no_i_c": "000000000",
                    "individuals_0_relationship_i_c": "wife_husband",
                },
            }
        ],
    },
    "correct": {
        "page": 1,
        "results": [
            {
                "id": 5,
                "flatten": {
                    "counters_rounds": "2",
                    "household_0_admin1_h_c": "UA01",
                    "household_0_admin2_h_c": "UA0102",
                    "household_0_admin3_h_c": "UA0102013",
                    "marketing_0_can_unicef_contact_you": "1",
                    "enumerator": "622984",
                    "individuals_0_id_type": "tax_id",
                    "individuals_0_role_i_c": "y",
                    "individuals_0_birth_date": "1991-01-01",
                    "individuals_0_gender_i_c": "male",
                    "individuals_0_patronymic": "as",
                    "individuals_0_phone_no_i_c": "+380123123123",
                    "individuals_0_tax_id_no_i_c": "000000000",
                    "individuals_0_disability_i_c": "n",
                    "individuals_0_given_name_i_c": "as",
                    "individuals_0_family_name_i_c": "sad",
                    "individuals_0_bank_account_h_f": "n",
                    "individuals_0_relationship_i_c": "head",
                },
            },
            {
                "id": 5,
                "flatten": {
                    "counters_rounds": "3",
                    "household_0_admin1_h_c": "UA01",
                    "household_0_admin2_h_c": "UA0102",
                    "household_0_admin3_h_c": "UA0102011",
                    "marketing_0_can_unicef_contact_you": "1",
                    "enumerator": "622984",
                    "individuals_0_role_i_c": "y",
                    "individuals_0_birth_date": "1994-02-12",
                    "individuals_0_gender_i_c": "female",
                    "individuals_0_patronymic": "Андріївна",
                    "individuals_0_bank_account": "UA264456452313575609876999999",
                    "individuals_0_phone_no_i_c": "0982580344",
                    "individuals_0_bank_name_h_f": "privatbank",
                    "individuals_0_tax_id_no_i_c": "3434564876",
                    "individuals_0_disability_i_c": "n",
                    "individuals_0_given_name_i_c": "Oksana",
                    "individuals_0_family_name_i_c": "Berezinska",
                    "individuals_0_bank_account_h_f": "y",
                    "individuals_0_relationship_i_c": "wife_husband",
                    "individuals_0_bank_account_number": "UA264456452313575609876999999",
                    "individuals_1_role_i_c": "n",
                    "individuals_1_birth_date": "1991-04-23",
                    "individuals_1_gender_i_c": "male",
                    "individuals_1_patronymic": "Романович",
                    "individuals_1_phone_no_i_c": "0732580344",
                    "individuals_1_bank_name_h_f": "privatbank",
                    "individuals_1_disability_i_c": "n",
                    "individuals_1_given_name_i_c": "Roman",
                    "individuals_1_family_name_i_c": "Berezinski",
                    "individuals_1_relationship_i_c": "head",
                    "individuals_2_role_i_c": "n",
                    "individuals_2_birth_date": "2013-06-21",
                    "individuals_2_gender_i_c": "female",
                    "individuals_2_patronymic": "Романівна",
                    "individuals_2_bank_name_h_f": "privatbank",
                    "individuals_2_disability_i_c": "n",
                    "individuals_2_given_name_i_c": "Злата",
                    "individuals_2_family_name_i_c": "Березінська",
                    "individuals_2_relationship_i_c": "son_daughter",
                    "individuals_2_birth_certificate_no_i_c": "СГ238745",
                },
            },
        ],
    },
}
