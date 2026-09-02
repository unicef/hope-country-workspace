from collections.abc import Callable

import pytest

from country_workspace.contrib.hope.rdi import load_mapping_from_api, map_members, map_role_value


@pytest.fixture
def errs() -> list[str]:
    return []


@pytest.fixture
def err(errs: list[str]) -> Callable[[str], None]:
    return errs.append


def test_load_mapping_from_api_filters_invalid_keys_and_values() -> None:
    errs: list[str] = []
    raw = {
        "1": "IND-25-0000.0051",
        "2": "IND-7.1",
        "x": "IND-25-0000.0051",
        "3": "IND-7",
        "4": 5,
        None: "IND-8-9.1",
    }

    assert load_mapping_from_api(raw, errs.append) == {
        1: "IND-25-0000.0051",
        2: "IND-7.1",
    }
    assert errs == [
        "Invalid mapping key 'x' -> 'IND-25-0000.0051'",
        "Invalid mapping value '3' -> 'IND-7'",
        "Invalid mapping value '4' -> 5",
        "Invalid mapping key None -> 'IND-8-9.1'",
    ]


@pytest.mark.parametrize(
    ("value", "mapping", "expected", "expected_error"),
    [
        (None, {}, None, None),
        (7, {7: "IND-7.1"}, "IND-7.1", None),
        (8, {7: "IND-7.1"}, None, "HH #100: no mapping for role=8"),
        ("IND-25-0000.0051", {}, "IND-25-0000.0051", None),
        ("IND-25", {}, None, "HH #100: invalid role='IND-25'"),
        ("foo", {}, None, "HH #100: invalid role='foo'"),
        (1.0, {1: "IND-1.1"}, None, "HH #100: invalid role=1.0"),
    ],
    ids=["none", "int_hit", "int_miss", "tag_ok", "tag_almost", "str_bad", "float_bad"],
)
def test_map_role_value(value, mapping: dict[int, str], expected: str | None, expected_error: str | None) -> None:
    errs: list[str] = []

    assert map_role_value(mapping, errs.append, 100, "role", value) == expected
    assert errs == ([] if expected_error is None else [expected_error])


@pytest.mark.parametrize(
    ("mapping", "member_ids", "hh_pk", "expected", "expected_errors"),
    [
        (
            {1: "IND-1.1", 3: "IND-3.1"},
            [1, 2, 3, 4],
            777,
            ["IND-1.1", "IND-3.1"],
            ["HH #777: no mapping for member ids [2, 4]"],
        ),
        (
            {1: "IND-1.1", 2: "IND-2.1"},
            [1, 2],
            5,
            ["IND-1.1", "IND-2.1"],
            [],
        ),
        ({}, [], 9, [], []),
    ],
    ids=["missing", "all_mapped", "empty"],
)
def test_map_members(
    mapping: dict[int, str],
    member_ids: list[int],
    hh_pk: int,
    expected: list[str],
    expected_errors: list[str],
) -> None:
    errs: list[str] = []

    assert map_members(mapping, errs.append, hh_pk, member_ids) == expected
    assert errs == expected_errors
