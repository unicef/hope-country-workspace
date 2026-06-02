from unittest.mock import patch

import pytest
from django.utils import timezone
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
    collect_invalidations,
    invalidate_entities_on_datachecker_change,
)
from country_workspace.validators.registry import NoopValidator
from tests.extras.testutils.factories import (
    ProgramFactory,
    BatchFactory,
    HouseholdFactory,
    IndividualFactory,
    FieldDefinitionFactory,
    FieldsetFactory,
    FlexFieldFactory,
)
from tests.extras.testutils.factories.program import BeneficiaryGroupFactory
from tests.extras.testutils.factories.smart_fields import DataCheckerFactory

CHECKED = timezone.now()


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
def batch(program):
    return BatchFactory.create(program=program)


@pytest.fixture
def households(batch):
    HouseholdFactory.create_batch(10, batch=batch, errors={}, removed=False, last_checked=CHECKED)
    HouseholdFactory.create_batch(10, batch=batch, removed=True, last_checked=CHECKED)
    HouseholdFactory.create_batch(10, batch=batch, errors={"some_error": "details"}, last_checked=CHECKED)


@pytest.fixture
def individuals(batch):
    hh = HouseholdFactory.create(batch=batch, individuals=[])
    IndividualFactory.create_batch(10, household=hh, errors={}, removed=False, last_checked=CHECKED)
    IndividualFactory.create_batch(10, household=hh, removed=True, last_checked=CHECKED)
    IndividualFactory.create_batch(10, household=hh, errors={"some_error": "details"}, last_checked=CHECKED)


@pytest.fixture
def unchecked_households(batch):
    return HouseholdFactory.create_batch(3, batch=batch, errors={}, removed=False, individuals=[], last_checked=None)


@pytest.fixture
def unchecked_individuals(batch, unchecked_households):
    return IndividualFactory.create_batch(
        3, batch=batch, household=unchecked_households[0], errors={}, removed=False, last_checked=None
    )


@pytest.fixture
def checked_household(batch):
    return HouseholdFactory.create(batch=batch, errors={}, removed=False, individuals=[], last_checked=CHECKED)


@pytest.fixture
def checked_individual(batch, checked_household):
    return IndividualFactory.create(
        batch=batch, household=checked_household, errors={}, removed=False, last_checked=CHECKED
    )


@pytest.fixture
def hh_validated_households(hh_datachecker):
    program = ProgramFactory.create(household_checker=hh_datachecker)
    batch = BatchFactory.create(program=program)
    validated = HouseholdFactory.create_batch(
        3, batch=batch, errors={}, removed=False, individuals=[], last_checked=CHECKED
    )
    HouseholdFactory.create(batch=batch, errors={"x": 1}, removed=False, individuals=[], last_checked=CHECKED)
    HouseholdFactory.create(batch=batch, errors={}, removed=True, individuals=[], last_checked=CHECKED)
    return validated


def test_process_datachecker_change_updates_households(hh_datachecker, hh_validated_households):
    _process_datachecker_change(hh_datachecker)

    for hh in hh_validated_households:
        hh.refresh_from_db()
        assert hh.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert hh.last_checked is None


@pytest.fixture
def ind_validated_individuals(ind_datachecker):
    program = ProgramFactory.create(individual_checker=ind_datachecker)
    batch = BatchFactory.create(program=program)
    hh = HouseholdFactory.create(batch=batch, individuals=[])
    validated = IndividualFactory.create_batch(3, household=hh, errors={}, removed=False, last_checked=CHECKED)
    ind_1 = IndividualFactory.create(household=hh, errors={"x": 1}, removed=False, last_checked=CHECKED)
    IndividualFactory.create(household=hh, errors={}, removed=True, last_checked=CHECKED)
    return [*validated, ind_1]


def test_process_datachecker_change_updates_individuals(ind_datachecker, ind_validated_individuals):
    _process_datachecker_change(ind_datachecker)

    for ind in ind_validated_individuals:
        ind.refresh_from_db()
        assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert ind.last_checked is None


@pytest.fixture
def people_validated_individuals(people_datachecker):
    bg = BeneficiaryGroupFactory(master_detail=False)
    program = ProgramFactory.create(individual_checker=people_datachecker, beneficiary_group=bg)
    batch = BatchFactory.create(program=program)
    validated = IndividualFactory.create_batch(
        3, batch=batch, household=None, errors={}, removed=False, last_checked=CHECKED
    )
    ind_1 = IndividualFactory.create(batch=batch, household=None, errors={"x": 1}, removed=False, last_checked=CHECKED)
    IndividualFactory.create(batch=batch, household=None, errors={}, removed=True, last_checked=CHECKED)
    return [*validated, ind_1]


def test_process_datachecker_change_updates_people(people_datachecker, people_validated_individuals):
    _process_datachecker_change(people_datachecker)

    for ind in people_validated_individuals:
        ind.refresh_from_db()
        assert ind.errors == {"data_checker": "Invalidated due to DataChecker change."}
        assert ind.last_checked is None


def test_non_validated_entities_are_not_invalidated(
    hh_datachecker, ind_datachecker, unchecked_households, unchecked_individuals, checked_household, checked_individual
):
    _process_datachecker_change(hh_datachecker)
    _process_datachecker_change(ind_datachecker)

    for hh in unchecked_households:
        hh.refresh_from_db()
        assert hh.errors == {}
        assert hh.last_checked is None

    for ind in unchecked_individuals:
        ind.refresh_from_db()
        assert ind.errors == {}
        assert ind.last_checked is None

    checked_household.refresh_from_db()
    assert checked_household.errors == {"data_checker": "Invalidated due to DataChecker change."}
    assert checked_household.last_checked is None

    checked_individual.refresh_from_db()
    assert checked_individual.errors == {"data_checker": "Invalidated due to DataChecker change."}
    assert checked_individual.last_checked is None


def test_process_datachecker_change_ignores_unknown_checker_name():
    dc = DataChecker.objects.create(name="SOME_UNKNOWN")
    _process_datachecker_change(dc)


@pytest.fixture
def hh_fieldsets(hh_datachecker):
    fs = FieldsetFactory.create()
    fs_2 = FieldsetFactory.create()
    hh_datachecker.fieldsets.add(*[fs, fs_2])
    return fs, fs_2


@pytest.fixture
def ind_dcfieldset(ind_datachecker):
    fs = FieldsetFactory.create()
    return DataCheckerFieldset.objects.create(checker=ind_datachecker, fieldset=fs)


@pytest.fixture
def hh_flexfield(hh_datachecker):
    fs = FieldsetFactory.create()
    hh_datachecker.fieldsets.add(fs)
    return FlexFieldFactory.create(fieldset=fs)


def test_fieldset_update_triggers_processing(hh_datachecker, hh_fieldsets):
    fs, _ = hh_fieldsets
    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        fs.description = "Updated"
        fs.save(update_fields=["description"])
        mocked.assert_called_once_with(dc=hh_datachecker)


def test_dcfieldset_update_triggers_processing(ind_datachecker, ind_dcfieldset):
    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        ind_dcfieldset.prefix = "p_"
        ind_dcfieldset.save(update_fields=["prefix"])
        mocked.assert_called_once_with(dc=ind_datachecker)


def test_datachecker_update_does_not_trigger_processing(hh_datachecker):
    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        hh_datachecker.description = "Updated"
        hh_datachecker.save(update_fields=["description"])
        mocked.assert_not_called()


def test_flexfield_update_triggers_processing(hh_datachecker, hh_flexfield):
    with patch("country_workspace.signals._process_datachecker_change") as mocked:
        hh_flexfield.attrs = {"label": "Updated"}
        hh_flexfield.save(update_fields=["attrs"])
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


@pytest.fixture
def validator_change_program(hh_datachecker, ind_datachecker):
    program = ProgramFactory.create(
        household_checker=hh_datachecker, individual_checker=ind_datachecker, beneficiary_validator=fqn(NoopValidator)
    )
    batch = BatchFactory.create(program=program)
    valid_hhs = HouseholdFactory.create_batch(3, batch=batch, individuals=[], last_checked=CHECKED)
    HouseholdFactory.create_batch(4, batch=batch, individuals=[], errors={"x": 1}, removed=False, last_checked=CHECKED)
    HouseholdFactory.create_batch(5, batch=batch, individuals=[], removed=True, last_checked=CHECKED)

    for hh in valid_hhs:
        IndividualFactory.create_batch(3, batch=batch, household=hh, errors={}, removed=False, last_checked=CHECKED)
        IndividualFactory.create_batch(
            4, batch=batch, household=hh, errors={"x": 1}, removed=False, last_checked=CHECKED
        )
        IndividualFactory.create_batch(5, batch=batch, household=hh, errors={}, removed=True, last_checked=CHECKED)

    return program


def test_invalidation_on_beneficiary_validator_change(validator_change_program):
    validator_change_program.beneficiary_validator = fqn(FullHouseholdValidator)
    validator_change_program.save()

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
    assert ind_invalidated_count == 7 * 3


@pytest.fixture
def households_with_errors(batch):
    return HouseholdFactory.create_batch(
        10, batch=batch, individuals=[], errors={"x": "1"}, removed=False, last_checked=CHECKED
    )


def test_no_invalidation_on_other_field_change(program, households_with_errors):
    program.name = "New Program Name"
    program.save()

    for hh in households_with_errors:
        hh.refresh_from_db()
        assert hh.errors == {"x": "1"}


@pytest.fixture
def synclog_for_refresh():
    from country_workspace.models import SyncLog
    from hope_flex_fields.models import FieldDefinition
    from django.contrib.contenttypes.models import ContentType

    fd = FieldDefinitionFactory.create(name="test-fd", attrs={"choices": [["x", "X"]]})
    fd.refresh_from_db()
    fs = FieldsetFactory.create()
    ff = FlexFieldFactory.create(fieldset=fs, definition=fd, attrs={})
    ff.refresh_from_db()
    ct = ContentType.objects.get_for_model(FieldDefinition)
    sync = SyncLog.objects.create(content_type=ct, object_id=fd.pk, data={"remote_url": "lookups/test"})
    return sync, fd, ff


def test_collect_invalidations_deduplicates_and_flushes(hh_datachecker):
    program = ProgramFactory.create(household_checker=hh_datachecker)
    batch = BatchFactory.create(program=program)
    hh = HouseholdFactory.create(batch=batch, errors={}, removed=False, individuals=[], last_checked=CHECKED)

    with collect_invalidations():
        _process_datachecker_change(hh_datachecker)
        _process_datachecker_change(hh_datachecker)

        hh.refresh_from_db()
        assert hh.last_checked == CHECKED

    hh.refresh_from_db()
    assert hh.last_checked is None
    assert hh.errors == {"data_checker": "Invalidated due to DataChecker change."}


def test_collect_invalidations_empty():
    with patch("country_workspace.signals._process_program") as mock_process:
        with collect_invalidations():
            pass
        mock_process.assert_not_called()


def test_synclog_refresh_skips_save_when_attrs_unchanged(synclog_for_refresh):
    sync, fd, ff = synclog_for_refresh
    existing_choices = dict(fd.attrs.get("choices", []))

    with patch("country_workspace.contrib.hope.client.HopeClient.get_lookup", return_value=existing_choices):
        with patch("country_workspace.signals._process_datachecker_change"):
            sync.refresh()

    fd.refresh_from_db()
    ff.refresh_from_db()
    assert fd.attrs["choices"] == [list(pair) for pair in existing_choices.items()]


def test_synclog_refresh_saves_when_attrs_changed(synclog_for_refresh):
    sync, fd, _ff = synclog_for_refresh

    with patch("country_workspace.contrib.hope.client.HopeClient.get_lookup", return_value={"new": "New"}):
        with patch("country_workspace.signals._process_datachecker_change"):
            sync.refresh()

    fd.refresh_from_db()
    assert fd.attrs["choices"] == [["new", "New"]]


@pytest.fixture
def synclog_for_manager_refresh():
    from country_workspace.models import SyncLog
    from hope_flex_fields.models import FieldDefinition
    from django.contrib.contenttypes.models import ContentType

    fd = FieldDefinitionFactory.create(name="test-mgr-fd", attrs={"choices": [["a", "A"]]})
    fd.refresh_from_db()
    ct = ContentType.objects.get_for_model(FieldDefinition)
    return SyncLog.objects.create(content_type=ct, object_id=fd.pk, data={"remote_url": "lookups/test"})


def test_synclog_manager_refresh_iterates_all_records(synclog_for_manager_refresh):
    from country_workspace.models import SyncLog

    with patch("country_workspace.contrib.hope.client.HopeClient.get_lookup", return_value={"b": "B"}):
        SyncLog.objects.refresh()

    fd = synclog_for_manager_refresh.content_object
    fd.refresh_from_db()
    assert fd.attrs["choices"] == [["b", "B"]]


def test_signal_handler_ignores_unrecognised_instance_type():
    class _Unrelated:
        pass

    with patch("country_workspace.signals._process_program") as mock_process:
        invalidate_entities_on_datachecker_change(sender=_Unrelated, instance=_Unrelated())
        mock_process.assert_not_called()


def test_datachecker_save_does_not_invalidate_entities(hh_datachecker, checked_household):
    hh_datachecker.description = "Changed description"
    hh_datachecker.save()

    checked_household.refresh_from_db()
    assert checked_household.last_checked == CHECKED
    assert checked_household.errors == {}


def test_collect_invalidations_deduplicates_multiple_signal_sources(program, hh_flexfield, checked_household):
    fs = hh_flexfield.fieldset

    with patch("country_workspace.signals._process_program") as mock_process:
        with collect_invalidations():
            hh_flexfield.attrs = {"label": "New"}
            hh_flexfield.save(update_fields=["attrs"])

            fs.description = "Updated"
            fs.save(update_fields=["description"])

        mock_process.assert_called_once_with(program=program)
