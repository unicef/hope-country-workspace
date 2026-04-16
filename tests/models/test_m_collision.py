import pytest

pytestmark = pytest.mark.django_db


def test_get_identity_field_name_no_checker():
    from country_workspace.contrib.hope.collision import get_identity_field_name

    assert get_identity_field_name(None) is None


def test_get_identity_field_name_checker_without_identity_field(plain_checker):
    from country_workspace.contrib.hope.collision import get_identity_field_name

    assert get_identity_field_name(plain_checker) is None


def test_get_identity_field_name_returns_field_name(identity_checker):
    from country_workspace.contrib.hope.collision import get_identity_field_name

    assert get_identity_field_name(identity_checker) == "uid"


def test_detect_and_mark_no_identity_field_is_noop(hh_no_checker):
    """When the program has no IdentityField checker, no records are marked."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    detect_and_mark_collisions_for_batch(hh_no_checker.batch)
    hh_no_checker.refresh_from_db()
    assert "identity" not in hh_no_checker.errors


def test_detect_and_mark_unique_values_in_batch_not_marked(batch, hh_unique_uid):
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    detect_and_mark_collisions_for_batch(batch)
    hh_unique_uid.refresh_from_db()
    assert "identity" not in hh_unique_uid.errors


def test_detect_and_mark_within_batch_duplicates(batch, hh_dup_pair):
    """Two records in the same batch sharing an identity value are both marked."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh1, hh2 = hh_dup_pair
    detect_and_mark_collisions_for_batch(batch)

    hh1.refresh_from_db()
    hh2.refresh_from_db()
    assert "identity" in hh1.errors
    assert "DUP" in hh1.errors["identity"]
    assert "identity" in hh2.errors
    assert "DUP" in hh2.errors["identity"]


def test_detect_and_mark_cross_batch_is_not_cw_concern(hh_cross_batch_pair):
    """CW does NOT mark cross-batch collisions — HOPE handles those during merge."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    new_batch, incoming = hh_cross_batch_pair
    detect_and_mark_collisions_for_batch(new_batch)

    incoming.refresh_from_db()
    assert "identity" not in incoming.errors


def test_detect_and_mark_clears_stale_error_when_no_longer_duplicate(batch, hh_with_stale_error):
    """When a duplicate is resolved, the stale error is cleared on re-run."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    detect_and_mark_collisions_for_batch(batch)

    hh_with_stale_error.refresh_from_db()
    assert "identity" not in hh_with_stale_error.errors


def test_detect_and_mark_skips_empty_identity_values(batch, hh_empty_uid_pair):
    """Records with blank identity values are ignored."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh1, hh2 = hh_empty_uid_pair
    detect_and_mark_collisions_for_batch(batch)

    hh1.refresh_from_db()
    hh2.refresh_from_db()
    assert "identity" not in hh1.errors
    assert "identity" not in hh2.errors


def test_detect_and_mark_none_uid_is_noop(batch, hh_none_uid):
    """Branch: `if not records` — uid=None is excluded entirely by the ORM filter."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    detect_and_mark_collisions_for_batch(batch)

    hh_none_uid.refresh_from_db()
    assert "identity" not in hh_none_uid.errors


def test_detect_and_mark_zero_uid_hits_empty_values_branch(batch, hh_zero_uid):
    """Branch: `if not values: return` — uid=0 passes the DB filter but is falsy in Python."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    detect_and_mark_collisions_for_batch(batch)

    hh_zero_uid.refresh_from_db()
    assert "identity" not in hh_zero_uid.errors


def test_detect_and_mark_skips_save_when_error_already_up_to_date(batch, hh_dup_pair):
    """Branch: `if record.errors.get("identity") != msg` is False — no redundant save."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    msg = "Duplicate 'uid' value 'DUP' found within the same batch."
    _, hh2 = hh_dup_pair

    detect_and_mark_collisions_for_batch(batch)
    hh2.refresh_from_db()
    assert hh2.errors.get("identity") == msg
    last_checked = hh2.last_checked

    # Second run: error already matches — record must not be saved again.
    detect_and_mark_collisions_for_batch(batch)
    hh2.refresh_from_db()
    assert hh2.errors.get("identity") == msg
    assert hh2.last_checked == last_checked


def test_detect_and_mark_individual_checker_marks_within_batch_duplicate(ind_batch, ind_dup_pair):
    """The individual_checker branch marks within-batch duplicate individuals."""
    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    ind1, ind2 = ind_dup_pair
    detect_and_mark_collisions_for_batch(ind_batch)

    ind1.refresh_from_db()
    ind2.refresh_from_db()
    assert "identity" in ind1.errors
    assert "identity" in ind2.errors


def test_household_validate_with_checker_preserves_identity_error(hh_with_identity_error):
    """validate_with_checker must not wipe an identity error set during import."""
    assert hh_with_identity_error.validate_with_checker() is False
    hh_with_identity_error.refresh_from_db()
    assert "identity" in hh_with_identity_error.errors


def test_household_validate_with_checker_does_not_add_identity_error(hh_same_uid_pair_with_members):
    """validate_with_checker never introduces identity errors — only import does."""
    _, hh2 = hh_same_uid_pair_with_members
    hh2.validate_with_checker()
    hh2.refresh_from_db()
    assert "identity" not in hh2.errors


def test_individual_validate_with_checker_preserves_identity_error(ind_with_identity_error):
    """Individual.validate_with_checker must not wipe an identity error set during import."""
    assert ind_with_identity_error.validate_with_checker() is False
    ind_with_identity_error.refresh_from_db()
    assert "identity" in ind_with_identity_error.errors


def test_individual_validate_with_checker_does_not_add_identity_error(ind_same_uid_second):
    """Individual.validate_with_checker never introduces identity errors."""
    ind_same_uid_second.validate_with_checker()
    ind_same_uid_second.refresh_from_db()
    assert "identity" not in ind_same_uid_second.errors


def test_individual_validate_with_checker_no_identity_checker_no_error(ind_no_checker):
    """When there is no IdentityField checker, no identity error appears after validation."""
    ind_no_checker.validate_with_checker()
    ind_no_checker.refresh_from_db()
    assert "identity" not in ind_no_checker.errors
