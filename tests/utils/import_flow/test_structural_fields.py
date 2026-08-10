from country_workspace.models.household import RELATIONSHIP_NON_BENEFICIARY
from country_workspace.utils.import_flow.structural_fields import (
    enforce_locked_fields,
    find_locked_field_changes,
)


def test_find_locked_field_changes_freezes_external_collector_structural_fields() -> None:
    current = {
        "relationship": RELATIONSHIP_NON_BENEFICIARY,
        "role": "PRIMARY",
        "collector_id": 1,
        "given_name": "Ada",
    }
    new = {
        "relationship": "HEAD",
        "role": "ALTERNATE",
        "collector_id": 2,
        "given_name": "Ada",
        "phone_no": "1",
    }

    assert find_locked_field_changes(current, new) == {
        "relationship": (RELATIONSHIP_NON_BENEFICIARY, "HEAD"),
        "role": ("PRIMARY", "ALTERNATE"),
        "collector_id": (1, 2),
    }


def test_find_locked_field_changes_allows_unrelated_external_collector_edits() -> None:
    current = {"relationship": RELATIONSHIP_NON_BENEFICIARY, "given_name": "Ada"}
    new = {"relationship": RELATIONSHIP_NON_BENEFICIARY, "given_name": "Ada", "phone_no": "1"}

    assert find_locked_field_changes(current, new) == {}


def test_find_locked_field_changes_allows_member_role_and_collector_id() -> None:
    current = {"relationship": "HEAD", "role": "NO_ROLE", "collector_id": None}
    new = {"relationship": "HEAD", "role": "PRIMARY", "collector_id": 9}

    assert find_locked_field_changes(current, new) == {}


def test_find_locked_field_changes_blocks_member_to_external_collector() -> None:
    current = {"relationship": "HEAD", "role": "PRIMARY"}
    new = {"relationship": RELATIONSHIP_NON_BENEFICIARY, "role": "PRIMARY"}

    assert find_locked_field_changes(current, new) == {
        "relationship": ("HEAD", RELATIONSHIP_NON_BENEFICIARY),
    }


def test_enforce_locked_fields_reverts_blocked_keys_and_keeps_allowed() -> None:
    current = {
        "relationship": RELATIONSHIP_NON_BENEFICIARY,
        "role": "PRIMARY",
        "given_name": "Ada",
    }
    new = {
        "relationship": "HEAD",
        "role": "ALTERNATE",
        "given_name": "Ada",
        "phone_no": "1",
    }

    assert enforce_locked_fields("collector", current, new) == {
        "relationship": RELATIONSHIP_NON_BENEFICIARY,
        "role": "PRIMARY",
        "given_name": "Ada",
        "phone_no": "1",
    }


def test_enforce_locked_fields_removes_key_missing_from_current() -> None:
    current = {"relationship": "HEAD"}
    new = {"relationship": RELATIONSHIP_NON_BENEFICIARY, "role": "PRIMARY"}

    assert enforce_locked_fields("member", current, new) == {"role": "PRIMARY", "relationship": "HEAD"}
