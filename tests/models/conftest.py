from __future__ import annotations

import pytest


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
def batch(program_with_hh_checker):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program_with_hh_checker)
