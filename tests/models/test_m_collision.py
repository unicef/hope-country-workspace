from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _make_identity_checker(field_name: str = "national_id"):
    """Return a DataChecker whose first flex-field is an IdentityField."""
    from hope_flex_fields.fields import IdentityField
    from testutils.factories import DataCheckerFactory, FieldDefinitionFactory, FieldsetFactory, FlexFieldFactory

    fd = FieldDefinitionFactory(name=f"fd_identity_{field_name}", field_type=IdentityField)
    fs = FieldsetFactory()
    FlexFieldFactory(name=field_name, fieldset=fs, definition=fd)
    checker = DataCheckerFactory()
    checker.fieldsets.add(fs)
    return checker


# ---------------------------------------------------------------------------
# IdentityField — disabled
# ---------------------------------------------------------------------------


def test_identity_field_is_disabled():
    """IdentityField must not be editable (disabled=True)."""
    from hope_flex_fields.fields import IdentityField

    field = IdentityField()
    assert field.disabled is True


# ---------------------------------------------------------------------------
# get_identity_field_name
# ---------------------------------------------------------------------------


def test_get_identity_field_name_no_checker():
    from country_workspace.utils.collision import get_identity_field_name

    assert get_identity_field_name(None) is None


def test_get_identity_field_name_checker_without_identity_field():
    from testutils.factories import DataCheckerFactory

    from country_workspace.utils.collision import get_identity_field_name

    checker = DataCheckerFactory()
    assert get_identity_field_name(checker) is None


def test_get_identity_field_name_returns_field_name():
    from country_workspace.utils.collision import get_identity_field_name

    checker = _make_identity_checker("passport_no")
    assert get_identity_field_name(checker) == "passport_no"


# ---------------------------------------------------------------------------
# detect_and_mark_collisions_for_batch — household checker
# ---------------------------------------------------------------------------


def test_detect_and_mark_no_identity_field_is_noop():
    """When the program checker has no IdentityField, no records are marked."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    hh = CountryHouseholdFactory()
    batch = hh.batch
    detect_and_mark_collisions_for_batch(batch)
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_unique_values_in_batch_not_marked():
    """Records with unique identity values within the batch are not marked."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "UNIQUE-001"})
    detect_and_mark_collisions_for_batch(batch)
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_within_batch_duplicates():
    """Two records in the same batch with the same identity value are both marked."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})

    detect_and_mark_collisions_for_batch(batch)

    hh1.refresh_from_db()
    hh2.refresh_from_db()
    assert "identity" in hh1.errors
    assert "DUP" in hh1.errors["identity"]
    assert "identity" in hh2.errors
    assert "DUP" in hh2.errors["identity"]


def test_detect_and_mark_cross_batch_is_not_cw_concern():
    """CW does NOT mark cross-batch collisions — HOPE handles those during merge."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)

    old_batch = CountryBatchFactory(program=program)
    new_batch = CountryBatchFactory(program=program)

    CountryHouseholdFactory(batch=old_batch, individuals=0, flex_fields={"uid": "SHARED-KEY"})
    incoming = CountryHouseholdFactory(batch=new_batch, individuals=0, flex_fields={"uid": "SHARED-KEY"})

    detect_and_mark_collisions_for_batch(new_batch)

    # Cross-batch collision is HOPE's responsibility, not CW's.
    incoming.refresh_from_db()
    assert "identity" not in incoming.errors


def test_detect_and_mark_clears_stale_error_when_no_longer_duplicate():
    """When a within-batch duplicate is resolved, the stale error is cleared on re-run."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    # Record has a stale identity error but is now the only one with this value.
    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SOLO"})
    hh.errors = {"identity": "stale error from a previous import run"}
    hh.save(update_fields=["errors"])

    detect_and_mark_collisions_for_batch(batch)

    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_skips_empty_identity_values():
    """Records with blank identity values are ignored."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": ""})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": ""})

    detect_and_mark_collisions_for_batch(batch)

    hh1.refresh_from_db()
    hh2.refresh_from_db()
    assert "identity" not in hh1.errors
    assert "identity" not in hh2.errors


def test_detect_and_mark_no_new_values_after_filtering_is_noop():
    """Branch: `if not values: return` — records have no meaningful identity value."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    # flex_fields has "uid" key but value is None — falsy guard filters it out.
    incoming = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": None})

    detect_and_mark_collisions_for_batch(batch)

    incoming.refresh_from_db()
    assert "identity" not in incoming.errors


# ---------------------------------------------------------------------------
# detect_and_mark_collisions_for_batch — individual checker
# ---------------------------------------------------------------------------


def test_detect_and_mark_individual_checker_marks_within_batch_duplicate():
    """Branch: `if ind_field := get_identity_field_name(program.individual_checker)` is taken."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program)
    hh = CountryHouseholdFactory(batch=batch, individuals=0)

    ind1 = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"uid": "IND-DUP"})
    ind2 = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"uid": "IND-DUP"})

    detect_and_mark_collisions_for_batch(batch)

    ind1.refresh_from_db()
    ind2.refresh_from_db()
    assert "identity" in ind1.errors
    assert "identity" in ind2.errors


# ---------------------------------------------------------------------------
# validate_with_checker — identity errors are preserved, never added by it
# ---------------------------------------------------------------------------


def test_household_validate_with_checker_preserves_identity_error():
    """validate_with_checker must not wipe an identity error set during import."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "KEY"})
    CountryIndividualFactory(batch=batch, household=hh)
    hh.errors = {"identity": "Duplicate 'uid' value 'KEY' found within the same batch."}
    hh.save(update_fields=["errors"])

    result = hh.validate_with_checker()

    assert result is False
    hh.refresh_from_db()
    assert "identity" in hh.errors


def test_household_validate_with_checker_does_not_add_identity_error():
    """validate_with_checker never introduces identity errors — only import does."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SAME"})
    CountryIndividualFactory(batch=batch, household=hh1)
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SAME"})
    CountryIndividualFactory(batch=batch, household=hh2)

    # validate_with_checker without a prior detect_and_mark_collisions_for_batch call.
    hh2.validate_with_checker()

    hh2.refresh_from_db()
    assert "identity" not in hh2.errors


def test_individual_validate_with_checker_preserves_identity_error():
    """Individual.validate_with_checker must not wipe an identity error set during import."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    checker = _make_identity_checker("uid")
    program = ProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    ind = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"uid": "IND-KEY"})
    ind.errors = {"identity": "Duplicate 'uid' value 'IND-KEY' found within the same batch."}
    ind.save(update_fields=["errors"])

    result = ind.validate_with_checker()

    assert result is False
    ind.refresh_from_db()
    assert "identity" in ind.errors


def test_individual_validate_with_checker_does_not_add_identity_error():
    """Individual.validate_with_checker never introduces identity errors."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    checker = _make_identity_checker("uid")
    program = ProgramFactory(individual_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    CountryIndividualFactory(batch=batch, household=hh, flex_fields={"uid": "IND-KEY"})
    ind2 = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"uid": "IND-KEY"})

    # validate_with_checker without a prior detect_and_mark_collisions_for_batch call.
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

    program = ProgramFactory()  # no IdentityField checker
    batch = CountryBatchFactory(program=program)
    hh = CountryHouseholdFactory(batch=batch, individuals=0)
    ind = CountryIndividualFactory(batch=batch, household=hh)

    ind.validate_with_checker()

    ind.refresh_from_db()
    assert "identity" not in ind.errors
