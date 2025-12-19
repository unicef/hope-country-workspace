from unittest.mock import patch

import pytest

from country_workspace.models import Batch, User
from country_workspace.workspaces.admin.batch_reprocessing import reprocess_batch


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


class TestReprocessBatchTask:
    def test_reprocess_batch_missing_config(self, user: User) -> None:
        from testutils.factories import AsyncJobFactory

        job = AsyncJobFactory(owner=user, config={})

        with pytest.raises(ValueError, match="batch_id is required"):
            reprocess_batch(job)

    def test_reprocess_batch_invalid_batch_id(self, user: User) -> None:
        from testutils.factories import AsyncJobFactory

        job = AsyncJobFactory(owner=user, config={"batch_id": 99999})

        with pytest.raises(Batch.DoesNotExist, match="Batch 99999 not found"):
            reprocess_batch(job)

    def test_reprocess_empty_batch(self, program, user: User) -> None:
        from testutils.factories import AsyncJobFactory, CountryBatchFactory

        empty_batch = CountryBatchFactory(program=program, country_office=program.country_office)
        job = AsyncJobFactory(
            program=program,
            batch=empty_batch,
            owner=user,
            config={"batch_id": empty_batch.pk},
        )

        result = reprocess_batch(job)

        assert result["batch_id"] == empty_batch.pk
        assert result["batch_name"] == empty_batch.name
        assert result["households"] == 0
        assert result["individuals"] == 0
        assert result["validation_jobs_created"] == 0

    def test_reprocess_batch_with_households(self, program, user: User, force_migrated_records) -> None:
        from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
            flex_fields={"size": 5},
        )
        batch = hh.batch

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["batch_id"] == batch.pk
            assert result["households"] == 1
            assert result["individuals"] == batch.individual_set.filter(removed=False).count()
            assert result["validation_jobs_created"] == int(result["households"] > 0) + int(result["individuals"] > 0)

            assert mock_create.call_count == result["validation_jobs_created"]

            calls = [c.kwargs for c in mock_create.call_args_list]
            hh_call = next(c for c in calls if c.get("description", "").endswith(" - Households"))
            assert "Reprocess batch" in hh_call["description"]
            assert hh_call["owner"] == user
            assert hh_call["program"] == program

            if result["individuals"] > 0:
                ind_call = next(c for c in calls if c.get("description", "").endswith(" - Individuals"))
                assert "Reprocess batch" in ind_call["description"]
                assert ind_call["owner"] == user
                assert ind_call["program"] == program

    def test_reprocess_batch_with_individuals_only(self, program, user: User, force_migrated_records) -> None:
        from testutils.factories import AsyncJobFactory, CountryIndividualFactory

        ind = CountryIndividualFactory(
            household=None,
            batch__program=program,
            batch__country_office=program.country_office,
            flex_fields={"full_name": "John Doe"},
        )
        batch = ind.batch

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["batch_id"] == batch.pk
            assert result["households"] == 0
            assert result["individuals"] == 1
            assert result["validation_jobs_created"] == 1
            mock_create.assert_called_once()

    def test_reprocess_batch_with_mixed_content(self, program, user: User, force_migrated_records) -> None:
        from testutils.factories import (
            AsyncJobFactory,
            CountryHouseholdFactory,
            CountryIndividualFactory,
        )

        # Create a batch with a household
        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
            flex_fields={"size": 3},
        )
        batch = hh.batch

        # Add a standalone individual to the same batch
        CountryIndividualFactory(
            household=None,
            batch=batch,
            flex_fields={"full_name": "Jane Smith"},
        )

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["batch_id"] == batch.pk
            assert result["households"] == 1
            assert result["individuals"] == batch.individual_set.filter(removed=False).count()
            assert result["validation_jobs_created"] == int(result["households"] > 0) + int(result["individuals"] > 0)

            assert mock_create.call_count == result["validation_jobs_created"]

    def test_reprocess_batch_multiple_households(self, program, user: User, force_migrated_records) -> None:
        from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

        # Create multiple households in the same batch
        hh1 = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
            flex_fields={"size": 3},
        )
        batch = hh1.batch

        CountryHouseholdFactory(
            batch=batch,
            flex_fields={"size": 5},
        )

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            result = reprocess_batch(job)

            assert result["households"] == 2
            assert result["individuals"] == batch.individual_set.filter(removed=False).count()
            assert result["validation_jobs_created"] == int(result["households"] > 0) + int(result["individuals"] > 0)
            assert mock_create.call_count == result["validation_jobs_created"]

    def test_reprocess_batch_queryset_prefetching(self, program, user: User, force_migrated_records) -> None:
        from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, CountryIndividualFactory

        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
            flex_fields={"size": 2},
        )
        batch = hh.batch

        # Add members to the household
        CountryIndividualFactory(household=hh, batch=batch, flex_fields={"full_name": "Member 1"})
        CountryIndividualFactory(household=hh, batch=batch, flex_fields={"full_name": "Member 2"})

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
            reprocess_batch(job)

            calls = [c.kwargs for c in mock_create.call_args_list]
            hh_call = next(c for c in calls if c.get("description", "").endswith(" - Households"))
            queryset = hh_call["queryset"]
            assert "members" in getattr(queryset, "_prefetch_related_lookups", ())

    def test_reprocess_batch_result_structure(self, program, user: User, force_migrated_records) -> None:
        from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
        )
        batch = hh.batch

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
            result = reprocess_batch(job)

            # Verify result has all expected keys
            assert "batch_id" in result
            assert "batch_name" in result
            assert "households" in result
            assert "individuals" in result
            assert "validation_jobs_created" in result

            # Verify types
            assert isinstance(result["batch_id"], int)
            assert isinstance(result["batch_name"], str)
            assert isinstance(result["households"], int)
            assert isinstance(result["individuals"], int)
            assert isinstance(result["validation_jobs_created"], int)
