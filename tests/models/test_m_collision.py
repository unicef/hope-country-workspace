import pytest

pytestmark = pytest.mark.django_db


def test_get_identity_field_name_no_checker():
    from country_workspace.contrib.hope.collision import get_identity_field_name

    assert get_identity_field_name(None) is None


def test_get_identity_field_name_checker_without_identity_field():
    from testutils.factories import DataCheckerFactory

    from country_workspace.contrib.hope.collision import get_identity_field_name

    checker = DataCheckerFactory()
    assert get_identity_field_name(checker) is None


def test_get_identity_field_name_returns_field_name(identity_checker):
    from country_workspace.contrib.hope.collision import get_identity_field_name

    assert get_identity_field_name(identity_checker) == "uid"


def test_detect_and_mark_no_identity_field_is_noop():
    """When the program checker has no IdentityField, no records are marked."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh = CountryHouseholdFactory()
    detect_and_mark_collisions_for_batch(hh.batch)
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_unique_values_in_batch_not_marked(batch):
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "UNIQUE-001"})
    detect_and_mark_collisions_for_batch(batch)
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_within_batch_duplicates(batch):
    """Two records in the same batch sharing an identity value are both marked."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})

    detect_and_mark_collisions_for_batch(batch)

    hh1.refresh_from_db()
    hh2.refresh_from_db()
    assert "identity" in hh1.errors
    assert "DUP" in hh1.errors["identity"]
    assert "identity" in hh2.errors
    assert "DUP" in hh2.errors["identity"]


def test_detect_and_mark_cross_batch_is_not_cw_concern(program_with_hh_checker):
    """CW does NOT mark cross-batch collisions — HOPE handles those during merge."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    old_batch = CountryBatchFactory(program=program_with_hh_checker)
    new_batch = CountryBatchFactory(program=program_with_hh_checker)

    CountryHouseholdFactory(batch=old_batch, individuals=0, flex_fields={"uid": "SHARED"})
    incoming = CountryHouseholdFactory(batch=new_batch, individuals=0, flex_fields={"uid": "SHARED"})

    detect_and_mark_collisions_for_batch(new_batch)

    incoming.refresh_from_db()
    assert "identity" not in incoming.errors


def test_detect_and_mark_clears_stale_error_when_no_longer_duplicate(batch):
    """When a duplicate is resolved, the stale error is cleared on re-run."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SOLO"})
    hh.errors = {"identity": "stale error from a previous import run"}
    hh.save(update_fields=["errors"])

    detect_and_mark_collisions_for_batch(batch)

    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_skips_empty_identity_values(batch):
    """Records with blank identity values are ignored."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": ""})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": ""})

    detect_and_mark_collisions_for_batch(batch)

    hh1.refresh_from_db()
    hh2.refresh_from_db()
    assert "identity" not in hh1.errors
    assert "identity" not in hh2.errors


def test_detect_and_mark_no_new_values_after_filtering_is_noop(batch):
    """Branch: `if not values: return` — records have a None identity value."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": None})

    detect_and_mark_collisions_for_batch(batch)

    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_records_pass_db_filter_but_values_list_empty(batch):
    """Branch: `if not values: return` — records pass the ORM filter (not None/empty string)
    but the Python-level falsy guard (flex_fields.get()) still yields an empty list."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    # 0 is not None and not "" so it passes the DB .exclude() filters,
    # but bool(0) is False so it is skipped by the list-comprehension guard,
    # making `values` empty and triggering the early return.
    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": 0})

    detect_and_mark_collisions_for_batch(batch)

    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_skips_save_when_error_already_up_to_date(batch):
    """Branch: `if record.errors.get("identity") != msg` is False — no redundant save.

    When the duplicate error is already stored verbatim, re-running detection
    must leave the record untouched (same errors dict, same last_checked).
    """
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    msg = "Duplicate 'uid' value 'DUP' found within the same batch."
    CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})

    # First run — sets the error and last_checked.
    detect_and_mark_collisions_for_batch(batch)
    hh2.refresh_from_db()
    assert hh2.errors.get("identity") == msg
    last_checked_after_first_run = hh2.last_checked

    # Second run — error already matches; record must not be saved again.
    detect_and_mark_collisions_for_batch(batch)
    hh2.refresh_from_db()
    assert hh2.errors.get("identity") == msg
    assert hh2.last_checked == last_checked_after_first_run


def test_detect_and_mark_individual_checker_marks_within_batch_duplicate(program_with_ind_checker):
    """The individual_checker branch marks within-batch duplicate individuals."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    from country_workspace.contrib.hope.collision import detect_and_mark_collisions_for_batch

    ind_batch = CountryBatchFactory(program=program_with_ind_checker)
    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)

    ind1 = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-DUP"})
    ind2 = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-DUP"})

    detect_and_mark_collisions_for_batch(ind_batch)

    ind1.refresh_from_db()
    ind2.refresh_from_db()
    assert "identity" in ind1.errors
    assert "identity" in ind2.errors


# ---------------------------------------------------------------------------
# validate_with_checker — identity errors preserved, never introduced
# ---------------------------------------------------------------------------


def test_household_validate_with_checker_preserves_identity_error(batch):
    """validate_with_checker must not wipe an identity error set during import."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "KEY"})
    CountryIndividualFactory(batch=batch, household=hh)
    hh.errors = {"identity": "Duplicate 'uid' value 'KEY' found within the same batch."}
    hh.save(update_fields=["errors"])

    assert hh.validate_with_checker() is False
    hh.refresh_from_db()
    assert "identity" in hh.errors


def test_household_validate_with_checker_does_not_add_identity_error(batch):
    """validate_with_checker never introduces identity errors — only import does."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SAME"})
    CountryIndividualFactory(batch=batch, household=hh1)
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SAME"})
    CountryIndividualFactory(batch=batch, household=hh2)

    hh2.validate_with_checker()

    hh2.refresh_from_db()
    assert "identity" not in hh2.errors


def test_individual_validate_with_checker_preserves_identity_error(program_with_ind_checker):
    """Individual.validate_with_checker must not wipe an identity error set during import."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    ind_batch = CountryBatchFactory(program=program_with_ind_checker)
    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)
    ind = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-KEY"})
    ind.errors = {"identity": "Duplicate 'uid' value 'IND-KEY' found within the same batch."}
    ind.save(update_fields=["errors"])

    assert ind.validate_with_checker() is False
    ind.refresh_from_db()
    assert "identity" in ind.errors


def test_individual_validate_with_checker_does_not_add_identity_error(program_with_ind_checker):
    """Individual.validate_with_checker never introduces identity errors."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    ind_batch = CountryBatchFactory(program=program_with_ind_checker)
    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)
    CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-KEY"})
    ind2 = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-KEY"})

    ind2.validate_with_checker()

    ind2.refresh_from_db()
    assert "identity" not in ind2.errors


def test_individual_validate_with_checker_no_identity_checker_no_error():
    """When there is no IdentityField checker, no identity error appears after validation."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    program = ProgramFactory()
    ind_batch = CountryBatchFactory(program=program)
    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)
    ind = CountryIndividualFactory(batch=ind_batch, household=hh)

    ind.validate_with_checker()

    ind.refresh_from_db()
    assert "identity" not in ind.errors
