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


def test_detect_and_mark_no_identity_field_is_noop():
    """When the program checker has no IdentityField, no records are marked."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    hh = CountryHouseholdFactory()
    batch = hh.batch
    # No IdentityField on checkers — should complete without marking anything
    detect_and_mark_collisions_for_batch(batch)
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_no_collision_when_values_are_unique():
    """Records with unique IdentityField values are not marked."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "UNIQUE-001"})
    detect_and_mark_collisions_for_batch(batch)
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_detect_and_mark_collision_marks_incoming_record():
    """A new-batch record whose IdentityField value exists in an earlier batch is marked."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)

    old_batch = CountryBatchFactory(program=program)
    new_batch = CountryBatchFactory(program=program)

    CountryHouseholdFactory(batch=old_batch, individuals=0, flex_fields={"uid": "SHARED-KEY"})
    incoming = CountryHouseholdFactory(batch=new_batch, individuals=0, flex_fields={"uid": "SHARED-KEY"})

    detect_and_mark_collisions_for_batch(new_batch)

    incoming.refresh_from_db()
    assert "identity" in incoming.errors
    assert "SHARED-KEY" in incoming.errors["identity"]


def test_detect_and_mark_does_not_mark_existing_record():
    """The pre-existing record (from an earlier batch) is never modified."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)

    old_batch = CountryBatchFactory(program=program)
    new_batch = CountryBatchFactory(program=program)

    existing = CountryHouseholdFactory(batch=old_batch, individuals=0, flex_fields={"uid": "SHARED-KEY"})
    CountryHouseholdFactory(batch=new_batch, individuals=0, flex_fields={"uid": "SHARED-KEY"})

    detect_and_mark_collisions_for_batch(new_batch)

    existing.refresh_from_db()
    assert "identity" not in existing.errors


def test_detect_and_mark_skips_empty_identity_values():
    """Records with blank IdentityField values are not matched or marked."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import detect_and_mark_collisions_for_batch

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)

    old_batch = CountryBatchFactory(program=program)
    new_batch = CountryBatchFactory(program=program)

    CountryHouseholdFactory(batch=old_batch, individuals=0, flex_fields={"uid": ""})
    incoming = CountryHouseholdFactory(batch=new_batch, individuals=0, flex_fields={"uid": ""})

    detect_and_mark_collisions_for_batch(new_batch)

    incoming.refresh_from_db()
    assert "identity" not in incoming.errors


def test_check_identity_collision_no_identity_field_clears_stale_error():
    """When the checker has no IdentityField, any stale 'identity' error is cleared."""
    from testutils.factories import CountryHouseholdFactory

    from country_workspace.utils.collision import check_identity_collision

    hh = CountryHouseholdFactory(individuals=0)
    hh.errors = {"identity": "stale error"}
    hh.save(update_fields=["errors"])

    result = check_identity_collision(hh)

    assert result is False
    assert "identity" not in hh.errors


def test_check_identity_collision_no_value_clears_stale_error():
    """When the record has no value for the IdentityField, stale error is cleared."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import check_identity_collision

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={})
    hh.errors = {"identity": "stale error"}
    hh.save(update_fields=["errors"])

    result = check_identity_collision(hh)

    assert result is False
    assert "identity" not in hh.errors


def test_check_identity_collision_detects_duplicate():
    """Returns True and sets errors['identity'] when a duplicate exists."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import check_identity_collision

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP-KEY"})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP-KEY"})

    result = check_identity_collision(hh2)

    assert result is True
    assert "identity" in hh2.errors
    assert "DUP-KEY" in hh2.errors["identity"]


def test_check_identity_collision_clears_error_when_no_longer_colliding():
    """After a collision is resolved, the error is cleared and False returned."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, ProgramFactory

    from country_workspace.utils.collision import check_identity_collision

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    # Only one record — no collision
    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SOLO-KEY"})
    hh.errors = {"identity": "previous stale collision error"}
    hh.save(update_fields=["errors"])

    result = check_identity_collision(hh)

    assert result is False
    assert "identity" not in hh.errors


def test_household_validate_with_checker_collision_sets_and_saves_error():
    """validate_with_checker saves the record when a new identity error is added."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "MATCH"})
    CountryIndividualFactory(batch=batch, household=hh1)

    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "MATCH"})
    CountryIndividualFactory(batch=batch, household=hh2)

    result = hh2.validate_with_checker()

    assert result is False
    hh2.refresh_from_db()
    assert "identity" in hh2.errors


def test_household_validate_with_checker_collision_cleared_on_revalidation():
    """validate_with_checker clears the identity error once the collision is gone."""
    from testutils.factories import (
        CountryBatchFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        ProgramFactory,
    )

    checker = _make_identity_checker("uid")
    program = ProgramFactory(household_checker=checker)
    batch = CountryBatchFactory(program=program)

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SOLO"})
    CountryIndividualFactory(batch=batch, household=hh)
    hh.errors = {"identity": "stale"}
    hh.save(update_fields=["errors"])

    result = hh.validate_with_checker()

    assert result is True
    hh.refresh_from_db()
    assert "identity" not in hh.errors


def test_individual_validate_with_checker_collision_sets_and_saves_error():
    """Individual.validate_with_checker persists a collision error."""
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

    result = ind2.validate_with_checker()

    assert result is False
    ind2.refresh_from_db()
    assert "identity" in ind2.errors


def test_individual_validate_with_checker_collision_cleared_on_revalidation():
    """Individual.validate_with_checker clears the identity error when resolved."""
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
    ind = CountryIndividualFactory(batch=batch, household=hh, flex_fields={"uid": "IND-SOLO"})
    ind.errors = {"identity": "stale"}
    ind.save(update_fields=["errors"])

    result = ind.validate_with_checker()

    assert result is True
    ind.refresh_from_db()
    assert "identity" not in ind.errors


def test_individual_validate_with_checker_no_collision_no_identity_error():
    """When there is no collision, 'identity' is absent from errors after validation."""
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
