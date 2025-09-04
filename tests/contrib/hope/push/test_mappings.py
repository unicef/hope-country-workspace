import pytest

from country_workspace.contrib.hope.push.mappings import (
    load_mapping_from_api,
    map_role_value,
    map_members,
)


# ------------------------- load_mapping_from_api ------------------------


def test_load_mapping_from_api_ok_and_coercion(err, errs):
    raw = {"1": "IND-1", "2": 5}
    out = load_mapping_from_api(raw, err)
    assert out == {1: "IND-1", 2: "5"}
    assert errs == []


def test_load_mapping_from_api_logs_invalid_keys(err, errs):
    raw = {"x": "IND-X", "3": "IND-3", None: "IND-NONE"}
    out = load_mapping_from_api(raw, err)
    assert out[3] == "IND-3"
    # two invalid keys: 'x' and None
    assert len(errs) == 2
    assert "Invalid mapping key 'x' -> 'IND-X'" in errs[0]
    assert "Invalid mapping key" in errs[1]


# ------------------------------ map_role_value --------------------------


@pytest.mark.parametrize(
    ("value", "mapping", "expected", "err_sub"),
    [
        (None, {}, None, None),
        (7, {7: "IND-7"}, "IND-7", None),
        (8, {7: "IND-7"}, None, "no mapping for role=8"),
        ("IND-42.1", {}, "IND-42.1", None),  # valid tag per IND_TAG_RE
        ("IND-42", {}, None, "invalid role='IND-42'"),  # almost valid but lacks .digits
        ("foo", {}, None, "invalid role='foo'"),
        (1.0, {1: "IND-1"}, None, "invalid role=1.0"),
    ],
    ids=["none", "int_hit", "int_miss", "tag_ok", "tag_almost", "str_bad", "float_bad"],
)
def test_map_role_value_variants(err, errs, value, mapping, expected, err_sub):
    field = "role"
    hh_pk = 100
    out = map_role_value(mapping, err, hh_pk, field, value)
    assert out == expected
    if err_sub is None:
        assert errs == []
    else:
        assert any(err_sub in m for m in errs)


# ------------------------------- map_members ----------------------------


def test_map_members_collects_missing_once(err, errs):
    mapping = {1: "IND-1", 3: "IND-3"}
    out = map_members(mapping, err, 777, [1, 2, 3, 4])
    assert out == ["IND-1", "IND-3"]
    assert errs
    assert errs[-1] == "HH #777: no mapping for member ids [2, 4]"


def test_map_members_all_mapped(err, errs):
    mapping = {1: "IND-1", 2: "IND-2"}
    out = map_members(mapping, err, 5, [1, 2])
    assert out == ["IND-1", "IND-2"]
    assert errs == []


def test_map_members_empty(err, errs):
    out = map_members({}, err, 9, [])
    assert out == []
    assert errs == []
