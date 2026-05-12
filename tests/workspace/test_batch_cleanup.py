from unittest.mock import patch

import pytest

from country_workspace.models import Batch, Household, Individual
from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.workspaces.admin.batch_cleanup import batch_cleanup


pytestmark = [pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
    )


@pytest.fixture
def batch(program):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


@pytest.fixture
def batch_with_household(program):
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
    )
    return hh.batch, hh


@pytest.fixture
def batch_with_household_and_individual(batch_with_household):
    from testutils.factories import CountryIndividualFactory

    batch, hh = batch_with_household
    ind = CountryIndividualFactory(household=hh, batch=batch)
    return batch, hh, ind


@pytest.fixture
def two_batches_with_households(program):
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory

    batch1 = CountryBatchFactory(program=program, country_office=program.country_office)
    batch2 = CountryBatchFactory(program=program, country_office=program.country_office)
    CountryHouseholdFactory(batch=batch1)
    CountryHouseholdFactory(batch=batch2)
    return batch1, batch2


@pytest.fixture
def job_missing_config(user):
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(owner=user, config={})


@pytest.fixture
def job_nonexistent_batches(user):
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(owner=user, config={"batch_ids": [99999]})


@pytest.fixture
def job_for_batch(program, user, batch):
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(
        program=program,
        owner=user,
        config={"batch_ids": [batch.pk]},
    )


@pytest.fixture
def job_for_batch_with_records(program, user, batch_with_household_and_individual):
    from testutils.factories import AsyncJobFactory

    batch, _, _ = batch_with_household_and_individual
    return AsyncJobFactory(
        program=program,
        owner=user,
        config={"batch_ids": [batch.pk]},
    )


@pytest.fixture
def job_for_two_batches(program, user, two_batches_with_households):
    from testutils.factories import AsyncJobFactory

    batch1, batch2 = two_batches_with_households
    return AsyncJobFactory(
        program=program,
        owner=user,
        config={"batch_ids": [batch1.pk, batch2.pk]},
    )


def test_batch_cleanup_missing_config(job_missing_config) -> None:
    with pytest.raises(ValueError, match="batch_ids is required"):
        batch_cleanup(job_missing_config)


def test_batch_cleanup_no_matching_batches(job_nonexistent_batches) -> None:
    result = batch_cleanup(job_nonexistent_batches)

    assert result == {"batches": 0, "households": 0, "individuals": 0}


def test_batch_cleanup_empty_batch(job_for_batch, batch) -> None:
    result = batch_cleanup(job_for_batch)

    assert result["batches"] == 1
    assert result["households"] == 0
    assert result["individuals"] == 0
    assert not Batch.objects.filter(pk=batch.pk).exists()


def test_batch_cleanup_with_households_and_individuals(
    job_for_batch_with_records, batch_with_household_and_individual
) -> None:
    batch, hh, ind = batch_with_household_and_individual

    result = batch_cleanup(job_for_batch_with_records)

    assert result["batches"] == 1
    assert result["households"] == 1
    assert result["individuals"] >= 1
    assert not Batch.objects.filter(pk=batch.pk).exists()
    assert not Household.objects.filter(pk=hh.pk).exists()
    assert not Individual.objects.filter(pk=ind.pk).exists()


def test_batch_cleanup_multiple_batches(job_for_two_batches, two_batches_with_households) -> None:
    batch1, batch2 = two_batches_with_households

    result = batch_cleanup(job_for_two_batches)

    assert result["batches"] == 2
    assert result["households"] == 2
    assert not Batch.objects.filter(pk__in=[batch1.pk, batch2.pk]).exists()


def test_batch_cleanup_respects_cancellation(job_for_batch) -> None:
    with patch.object(job_for_batch, "ensure_not_cancelled", side_effect=GracefulJobCancellationError("cancelled")):
        with pytest.raises(GracefulJobCancellationError):
            batch_cleanup(job_for_batch)
