from unittest.mock import patch

import pytest
from hope_flex_fields.models import DataChecker
from hope_flex_fields.models import Fieldset, DataCheckerFieldset

from country_workspace.contrib.hope.constants import (
    HOUSEHOLD_CHECKER_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.models import Household
from country_workspace.signals import (
    _get_filtering_params,
    _get_qs_by_dc,
    _process_datachecker_change,
)
from tests.extras.testutils.factories import ProgramFactory, BatchFactory, HouseholdFactory, IndividualFactory
from tests.extras.testutils.factories.program import BeneficiaryGroupFactory


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
def datacheckers_list(hh_datachecker, ind_datachecker, people_datachecker):
    return [hh_datachecker, ind_datachecker, people_datachecker]


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


@pytest.fixture
def people_program(people_datachecker):
    bg = BeneficiaryGroupFactory(master_detail=False)
    return ProgramFactory.create(individual_checker=people_datachecker, beneficiary_group=bg)


@pytest.fixture
def people_individuals(people_program):
    batch = BatchFactory.create(program=people_program)
    IndividualFactory.create_batch(10, household=None, batch=batch, errors={}, removed=False)
    IndividualFactory.create_batch(10, household=None, batch=batch, removed=True)
    IndividualFactory.create_batch(10, household=None, batch=batch, errors={"some_error": "details"})


def test_filtering_params(datacheckers_list):
    for dc in datacheckers_list:
        params = _get_filtering_params(dc, "household" if dc.name == HOUSEHOLD_CHECKER_NAME else "individual")
        assert params == {
            f"batch__program__{'household' if dc.name == HOUSEHOLD_CHECKER_NAME else 'individual'}_checker": dc,
            "removed": False,
            "errors": {},
        }


def test_hh_queryset_evaluation_by_dc(hh_datachecker, households):
    qs = _get_qs_by_dc(hh_datachecker)
    assert qs.model == HouseholdFactory._meta.model
    assert qs.count() == 10
    assert Household.objects.count() == 30


def test_individual_queryset_evaluation_by_dc(ind_datachecker, individuals):
    qs = _get_qs_by_dc(ind_datachecker)
    assert qs.model == IndividualFactory._meta.model
    assert IndividualFactory._meta.model.objects.count() == 30
    assert qs.count() == 10


def test_people_queryset_evaluation_by_dc(people_datachecker, people_individuals):
    qs = _get_qs_by_dc(people_datachecker)
    assert qs.model == IndividualFactory._meta.model
    assert IndividualFactory._meta.model.objects.count() == 30
    assert qs.count() == 10


def test_invalid_dc_returns_none():
    invalid_dc = DataChecker.objects.create(name="Invalid Checker")
    qs = _get_qs_by_dc(invalid_dc)
    assert qs is None


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
    IndividualFactory.create(household=hh, errors={"x": 1}, removed=False)
    IndividualFactory.create(household=hh, errors={}, removed=True)

    _process_datachecker_change(ind_datachecker)

    for ind in valid:
        ind.refresh_from_db()
        assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert ind.last_checked is None


def test_process_datachecker_change_updates_people(people_datachecker):
    bg = BeneficiaryGroupFactory(master_detail=False)
    program = ProgramFactory.create(individual_checker=people_datachecker, beneficiary_group=bg)
    batch = BatchFactory.create(program=program)
    valid = IndividualFactory.create_batch(3, batch=batch, household=None, errors={}, removed=False)
    IndividualFactory.create(batch=batch, household=None, errors={"x": 1}, removed=False)
    IndividualFactory.create(batch=batch, household=None, errors={}, removed=True)

    _process_datachecker_change(people_datachecker)

    for ind in valid:
        ind.refresh_from_db()
        assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert ind.last_checked is None


def test_process_datachecker_change_ignores_unknown_checker_name():
    dc = DataChecker.objects.create(name="SOME_UNKNOWN")
    _process_datachecker_change(dc)


def test_fieldset_update_triggers_processing(hh_datachecker, monkeypatch):
    fs = Fieldset.objects.create(name="FS")
    DataCheckerFieldset.objects.create(checker=hh_datachecker, fieldset=fs)

    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        fs.description = "Updated"
        fs.save(update_fields=["description"])
        mocked.assert_called_once_with(dc=hh_datachecker)


def test_dcfieldset_update_triggers_processing(ind_datachecker):
    fs = Fieldset.objects.create(name="FS2")
    rel = DataCheckerFieldset.objects.create(checker=ind_datachecker, fieldset=fs)

    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        rel.prefix = "p_"
        rel.save(update_fields=["prefix"])
        mocked.assert_called_once_with(dc=ind_datachecker)


def test_dcfieldset_delete_triggers_processing(people_datachecker):
    fs = Fieldset.objects.create(name="FS3")
    rel = DataCheckerFieldset.objects.create(checker=people_datachecker, fieldset=fs)

    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        rel.delete()
        mocked.assert_called_once_with(people_datachecker)
