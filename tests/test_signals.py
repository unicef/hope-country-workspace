from unittest.mock import patch

import pytest
from hope_flex_fields.models import DataChecker
from hope_flex_fields.models import DataCheckerFieldset
from strategy_field.utils import fqn

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.contrib.hope.validators import FullHouseholdValidator
from country_workspace.signals import (
    _process_datachecker_change,
    invalidate_entities_on_datachecker_change,
)
from country_workspace.validators.registry import NoopValidator
from tests.extras.testutils.factories import (
    ProgramFactory,
    BatchFactory,
    HouseholdFactory,
    IndividualFactory,
    FieldsetFactory,
    FlexFieldFactory,
)
from tests.extras.testutils.factories.program import BeneficiaryGroupFactory
from tests.extras.testutils.factories.smart_fields import DataCheckerFactory


@pytest.fixture
def hh_datachecker():
    return DataChecker.objects.create(name=HOUSEHOLD_CHECKER_NAME)


@pytest.fixture
def ind_datachecker():
    return DataChecker.objects.create(name=INDIVIDUAL_CHECKER_NAME)


@pytest.fixture
def people_datachecker():
    return DataChecker.objects.create(name=PEOPLE_CHECKER_NAME)


@pytest.fixture
def program(hh_datachecker, ind_datachecker):
    return ProgramFactory.create(household_checker=hh_datachecker, individual_checker=ind_datachecker)


@pytest.fixture
def households(program):
    batch = BatchFactory.create(program=program)
    HouseholdFactory.create_batch(10, batch=batch, errors={}, removed=False)
    HouseholdFactory.create_batch(10, batch=batch, removed=True)
    HouseholdFactory.create_batch(10, batch=batch, errors={"some_error": "details"})


@pytest.fixture
def individuals(program):
    batch = BatchFactory.create(program=program)
    hh = HouseholdFactory.create(batch=batch, individuals=[])
    IndividualFactory.create_batch(10, household=hh, errors={}, removed=False)
    IndividualFactory.create_batch(10, household=hh, removed=True)
    IndividualFactory.create_batch(10, household=hh, errors={"some_error": "details"})


def test_process_datachecker_change_updates_households(hh_datachecker):
    program = ProgramFactory.create(household_checker=hh_datachecker)
    batch = BatchFactory.create(program=program)
    valid = HouseholdFactory.create_batch(3, batch=batch, errors={}, removed=False, individuals=[])
    HouseholdFactory.create(batch=batch, errors={"x": 1}, removed=False, individuals=[])
    HouseholdFactory.create(batch=batch, errors={}, removed=True, individuals=[])

    _process_datachecker_change(hh_datachecker)

    for hh in valid:
        hh.refresh_from_db()
        assert hh.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert hh.last_checked is None


def test_process_datachecker_change_updates_individuals(ind_datachecker):
    program = ProgramFactory.create(individual_checker=ind_datachecker)
    batch = BatchFactory.create(program=program)
    hh = HouseholdFactory.create(batch=batch, individuals=[])
    valid = IndividualFactory.create_batch(3, household=hh, errors={}, removed=False)
    ind_1 = IndividualFactory.create(household=hh, errors={"x": 1}, removed=False)
    IndividualFactory.create(household=hh, errors={}, removed=True)

    _process_datachecker_change(ind_datachecker)

    for ind in [*valid, ind_1]:
        ind.refresh_from_db()
        assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert ind.last_checked is None


def test_process_datachecker_change_updates_people(people_datachecker):
    bg = BeneficiaryGroupFactory(master_detail=False)
    program = ProgramFactory.create(individual_checker=people_datachecker, beneficiary_group=bg)
    batch = BatchFactory.create(program=program)
    valid = IndividualFactory.create_batch(3, batch=batch, household=None, errors={}, removed=False)
    ind_1 = IndividualFactory.create(batch=batch, household=None, errors={"x": 1}, removed=False)
    IndividualFactory.create(batch=batch, household=None, errors={}, removed=True)

    _process_datachecker_change(people_datachecker)

    for ind in [*valid, ind_1]:
        ind.refresh_from_db()
        assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert ind.last_checked is None


def test_process_datachecker_change_ignores_unknown_checker_name():
    dc = DataChecker.objects.create(name="SOME_UNKNOWN")
    _process_datachecker_change(dc)


def test_fieldset_update_triggers_processing(hh_datachecker):
    fs = FieldsetFactory.create()
    fs_2 = FieldsetFactory.create()
    hh_datachecker.fieldsets.add(*[fs, fs_2])

    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        fs.description = "Updated"
        fs.save(update_fields=["description"])
        mocked.assert_called_once_with(dc=hh_datachecker)


def test_dcfieldset_update_triggers_processing(ind_datachecker):
    fs = FieldsetFactory.create()
    rel = DataCheckerFieldset.objects.create(checker=ind_datachecker, fieldset=fs)

    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        rel.prefix = "p_"
        rel.save(update_fields=["prefix"])
        mocked.assert_called_once_with(dc=ind_datachecker)


def test_datachecker_update_triggers_processing(hh_datachecker):
    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        hh_datachecker.description = "Updated"
        hh_datachecker.save(update_fields=["description"])
        mocked.assert_called_once_with(dc=hh_datachecker)


def test_flexfield_update_triggers_processing(hh_datachecker):
    fs = FieldsetFactory.create()
    hh_datachecker.fieldsets.add(fs)
    ff = FlexFieldFactory.create(fieldset=fs)

    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        ff.attrs = {"label": "Updated"}
        ff.save(update_fields=["attrs"])
        mocked.assert_called_once_with(dc=hh_datachecker)


def _test_invalidation_on_checker_change(program, factory, checker_field):
    new_checker = DataCheckerFactory()
    setattr(program, checker_field, new_checker)
    program.save()

    entities_invalidated = 0
    for entity in factory._meta.model.objects.all():
        entity.refresh_from_db()
        if entity.errors:
            assert entity.errors == {"data_checker": "Invalidated due to DataChecker change."}
            assert entity.last_checked is None
            entities_invalidated += 1

    assert entities_invalidated == 20


def test_invalidation_on_hh_checker_change(program, households):
    _test_invalidation_on_checker_change(program, HouseholdFactory, checker_field="household_checker")


def test_invalidation_on_individual_checker_change(program, individuals):
    _test_invalidation_on_checker_change(program, IndividualFactory, checker_field="individual_checker")


def test_invalidation_on_beneficiary_validator_change(hh_datachecker, ind_datachecker):
    program = ProgramFactory.create(
        household_checker=hh_datachecker, individual_checker=ind_datachecker, beneficiary_validator=fqn(NoopValidator)
    )
    batch = BatchFactory.create(program=program)
    valid_hhs = HouseholdFactory.create_batch(3, batch=batch, individuals=[])
    HouseholdFactory.create_batch(4, batch=batch, individuals=[], errors={"x": 1}, removed=False)
    HouseholdFactory.create_batch(5, batch=batch, individuals=[], removed=True)

    for hh in valid_hhs:
        IndividualFactory.create_batch(3, batch=batch, household=hh, errors={}, removed=False)
        IndividualFactory.create_batch(4, batch=batch, household=hh, errors={"x": 1}, removed=False)
        IndividualFactory.create_batch(5, batch=batch, household=hh, errors={}, removed=True)

    program.beneficiary_validator = fqn(FullHouseholdValidator)
    program.save()

    hh_invalidated_count = 0
    ind_invalidated_count = 0
    for hh in HouseholdFactory._meta.model.objects.all():
        hh.refresh_from_db()
        if hh.errors:
            assert hh.errors == {"data_checker": "Invalidated due to DataChecker change."}
            assert hh.last_checked is None
            hh_invalidated_count += 1

    for ind in IndividualFactory._meta.model.objects.all():
        ind.refresh_from_db()
        if ind.errors:
            assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
            assert ind.last_checked is None
            ind_invalidated_count += 1

    assert hh_invalidated_count == 7
    assert ind_invalidated_count == 7 * 3  # 7 invalid across 3 valid households


def test_no_invalidation_on_other_field_change(program):
    batch = BatchFactory.create(program=program)
    HouseholdFactory.create_batch(10, batch=batch, individuals=[], errors={"x": "1"}, removed=False)

    program.name = "New Program Name"
    program.save()

    for hh in HouseholdFactory._meta.model.objects.all():
        hh.refresh_from_db()
        assert hh.errors == {"x": "1"}


def test_signal_handler_ignores_unrecognised_instance_type():
    class _Unrelated:
        pass

    with patch("country_workspace.signals._process_program") as mock_process:
        invalidate_entities_on_datachecker_change(sender=_Unrelated, instance=_Unrelated())
        mock_process.assert_not_called()
