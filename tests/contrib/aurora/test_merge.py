import pytest

from country_workspace.contrib.aurora.crypto import merge


def test_merge_adds_keys_only_present_in_b() -> None:
    a = {"first_name": "Alice"}
    b = {"last_name": "Smith"}

    assert merge(a, b) == {"first_name": "Alice", "last_name": "Smith"}


def test_merge_recurses_into_nested_dicts() -> None:
    a = {"household": {"admin1": "FO001"}}
    b = {"household": {"admin2": "FO001-01"}}

    assert merge(a, b) == {"household": {"admin1": "FO001", "admin2": "FO001-01"}}


def test_merge_keeps_identical_leaf_values() -> None:
    a = {"consent": True}
    b = {"consent": True}

    assert merge(a, b) == {"consent": True}


def test_merge_merges_lists_elementwise() -> None:
    a = {"individuals": [{"given_name": "Ada"}, {"given_name": "Bruno"}]}
    b = {"individuals": [{"family_name": "Lovelace"}, {"family_name": "Green"}]}

    result = merge(a, b)

    assert result == {
        "individuals": [
            {"given_name": "Ada", "family_name": "Lovelace"},
            {"given_name": "Bruno", "family_name": "Green"},
        ]
    }


def test_merge_overwrites_conflicting_leaf_when_update_true() -> None:
    a = {"given_name": "Ada"}
    b = {"given_name": "Grace"}

    assert merge(a, b, update=True) == {"given_name": "Grace"}


def test_merge_raises_on_conflict_when_update_false() -> None:
    a = {"given_name": "Ada"}
    b = {"given_name": "Grace"}

    with pytest.raises(ValueError, match="Conflict at given_name"):
        merge(a, b, update=False)


def test_merge_mutates_and_returns_first_argument() -> None:
    a = {"given_name": "Ada"}
    b = {"family_name": "Lovelace"}

    result = merge(a, b)

    assert result is a
