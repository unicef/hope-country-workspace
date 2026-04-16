from __future__ import annotations

import pytest


@pytest.fixture
def plain_checker():
    """A DataChecker with no IdentityField."""
    from testutils.factories import DataCheckerFactory

    return DataCheckerFactory()


@pytest.fixture
def identity_checker():
    """A DataChecker with a single IdentityField named 'uid'."""
    from hope_flex_fields.fields import IdentityField
    from testutils.factories import DataCheckerFactory, FieldDefinitionFactory, FieldsetFactory, FlexFieldFactory

    fd = FieldDefinitionFactory(name="fd_identity_uid", field_type=IdentityField)
    fs = FieldsetFactory()
    FlexFieldFactory(name="uid", fieldset=fs, definition=fd)
    checker = DataCheckerFactory()
    checker.fieldsets.add(fs)
    return checker


@pytest.fixture
def program_with_hh_checker(identity_checker):
    from testutils.factories import ProgramFactory

    return ProgramFactory(household_checker=identity_checker)


@pytest.fixture
def program_with_ind_checker(identity_checker):
    from testutils.factories import ProgramFactory

    return ProgramFactory(individual_checker=identity_checker)


@pytest.fixture
def program_no_checker():
    from testutils.factories import ProgramFactory

    return ProgramFactory()


@pytest.fixture
def batch(program_with_hh_checker):
    """A batch whose program has a household IdentityField checker."""
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program_with_hh_checker)


@pytest.fixture
def ind_batch(program_with_ind_checker):
    """A batch whose program has an individual IdentityField checker."""
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program_with_ind_checker)


@pytest.fixture
def batch_no_checker(program_no_checker):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program_no_checker)


@pytest.fixture
def hh_no_checker(batch_no_checker):
    """A household in a program without any IdentityField checker."""
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch=batch_no_checker, individuals=0)


@pytest.fixture
def hh_unique_uid(batch):
    """One household with a unique uid value."""
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "UNIQUE-001"})


@pytest.fixture
def hh_dup_pair(batch):
    """Two households in the same batch that share the same uid value."""
    from testutils.factories import CountryHouseholdFactory

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "DUP"})
    return hh1, hh2


@pytest.fixture
def hh_cross_batch_pair(program_with_hh_checker):
    """One household in an old batch, one in a new batch, both sharing the same uid."""
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory

    old_batch = CountryBatchFactory(program=program_with_hh_checker)
    new_batch = CountryBatchFactory(program=program_with_hh_checker)
    CountryHouseholdFactory(batch=old_batch, individuals=0, flex_fields={"uid": "SHARED"})
    incoming = CountryHouseholdFactory(batch=new_batch, individuals=0, flex_fields={"uid": "SHARED"})
    return new_batch, incoming


@pytest.fixture
def hh_with_stale_error(batch):
    """A household with a stale identity error and a unique uid (no real duplicate)."""
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SOLO"})
    hh.errors = {"identity": "stale error from a previous import run"}
    hh.save(update_fields=["errors"])
    return hh


@pytest.fixture
def hh_empty_uid_pair(batch):
    """Two households whose uid field is an empty string."""
    from testutils.factories import CountryHouseholdFactory

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": ""})
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": ""})
    return hh1, hh2


@pytest.fixture
def hh_none_uid(batch):
    """A household whose uid field is None (excluded by ORM filter — no records found)."""
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": None})


@pytest.fixture
def hh_zero_uid(batch):
    """A household whose uid is 0 — passes DB filter but is falsy in Python."""
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": 0})


@pytest.fixture
def hh_with_identity_error(batch):
    """A household whose identity error is already set to the canonical message."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "KEY"})
    CountryIndividualFactory(batch=batch, household=hh)
    hh.errors = {"identity": "Duplicate 'uid' value 'KEY' found within the same batch."}
    hh.save(update_fields=["errors"])
    return hh


@pytest.fixture
def hh_same_uid_pair_with_members(batch):
    """Two households with the same uid, each with one member individual."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh1 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SAME"})
    CountryIndividualFactory(batch=batch, household=hh1)
    hh2 = CountryHouseholdFactory(batch=batch, individuals=0, flex_fields={"uid": "SAME"})
    CountryIndividualFactory(batch=batch, household=hh2)
    return hh1, hh2


@pytest.fixture
def ind_dup_pair(ind_batch):
    """Two individuals in the same batch that share the same uid value."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)
    ind1 = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-DUP"})
    ind2 = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-DUP"})
    return ind1, ind2


@pytest.fixture
def ind_with_identity_error(ind_batch):
    """An individual whose identity error is already set to the canonical message."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)
    ind = CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-KEY"})
    ind.errors = {"identity": "Duplicate 'uid' value 'IND-KEY' found within the same batch."}
    ind.save(update_fields=["errors"])
    return ind


@pytest.fixture
def ind_same_uid_second(ind_batch):
    """The second of two individuals sharing the same uid (the one to validate)."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=ind_batch, individuals=0)
    CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-KEY"})
    return CountryIndividualFactory(batch=ind_batch, household=hh, flex_fields={"uid": "IND-KEY"})


@pytest.fixture
def ind_no_checker(batch_no_checker):
    """An individual in a program without any IdentityField checker."""
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(batch=batch_no_checker, individuals=0)
    return CountryIndividualFactory(batch=batch_no_checker, household=hh)
