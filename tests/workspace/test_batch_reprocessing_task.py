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
        assert result.get("households", 0) == 0
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
            households_count = result.get("households", 0)
            is_master_detail = batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail
            if is_master_detail:
                assert households_count == 1
            assert result["individuals"] == batch.individual_set.filter(removed=False).count()
            expected_jobs = int(households_count > 0 and is_master_detail) + int(result["individuals"] > 0)
            assert result["validation_jobs_created"] == expected_jobs

            assert mock_create.call_count == result["validation_jobs_created"]

            calls = [c.kwargs for c in mock_create.call_args_list]
            if households_count > 0:
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
            if batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail:
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
            households_count = result.get("households", 0)
            is_master_detail = batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail
            if is_master_detail:
                assert households_count == 1
            assert result["individuals"] == batch.individual_set.filter(removed=False).count()
            expected_jobs = int(households_count > 0 and is_master_detail) + int(result["individuals"] > 0)
            assert result["validation_jobs_created"] == expected_jobs

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

            is_master_detail = batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail
            if is_master_detail:
                assert result.get("households", 0) == 2
            assert result["individuals"] == batch.individual_set.filter(removed=False).count()
            households_count = result.get("households", 0)
            expected_jobs = int(households_count > 0 and is_master_detail) + int(result["individuals"] > 0)
            assert result["validation_jobs_created"] == expected_jobs
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

            is_master_detail = batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail
            calls = [c.kwargs for c in mock_create.call_args_list]
            if is_master_detail:
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
            assert "individuals" in result
            assert "validation_jobs_created" in result

            # Verify types
            assert isinstance(result["batch_id"], int)
            assert isinstance(result["batch_name"], str)
            assert isinstance(result["individuals"], int)
            assert isinstance(result["validation_jobs_created"], int)

            # Households key is only present when master_detail is True
            if batch.program.beneficiary_group and batch.program.beneficiary_group.master_detail:
                assert "households" in result
                assert isinstance(result["households"], int)

    def test_reprocess_batch_household_mapping_not_found(self, program, user: User, force_migrated_records) -> None:
        """Test reprocess_batch handles MappingImporter.DoesNotExist for household mapping."""
        from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
            raw_data={"col1": "value1"},
        )
        batch = hh.batch

        # Set master_detail to True so household mapping is attempted
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(master_detail=True)
        batch.program.beneficiary_group = bg
        batch.program.save()

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk, "household_mapping_id": 99999},  # Non-existent mapping
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
            # Should not raise, just log warning and skip mapping
            result = reprocess_batch(job)

            assert result["batch_id"] == batch.pk
            assert result.get("mapped_households", 0) == 0

    def test_reprocess_batch_individual_mapping_not_found(self, program, user: User, force_migrated_records) -> None:
        """Test reprocess_batch handles MappingImporter.DoesNotExist for individual mapping."""
        from testutils.factories import AsyncJobFactory, CountryIndividualFactory

        ind = CountryIndividualFactory(
            household=None,
            batch__program=program,
            batch__country_office=program.country_office,
            raw_data={"col1": "value1"},
        )
        batch = ind.batch

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk, "individual_mapping_id": 99999},  # Non-existent mapping
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
            # Should not raise, just log warning and skip mapping
            result = reprocess_batch(job)

            assert result["batch_id"] == batch.pk
            assert result.get("mapped_individuals", 0) == 0

    def test_apply_mapping_no_raw_data(self, program, user: User) -> None:
        """Test _apply_mapping returns False when record has no raw_data."""
        from country_workspace.workspaces.admin.batch_reprocessing import _apply_mapping
        from testutils.factories import CountryHouseholdFactory, MappingImporterFactory

        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
        )
        hh.raw_data = {}
        hh.save(update_fields=["raw_data"])

        mapping = MappingImporterFactory(rules="col1=field1")

        result = _apply_mapping(hh, mapping)

        assert result is False
        # Record should not be modified
        hh.refresh_from_db()
        assert hh.flex_fields != {"field1": "value1"}

    def test_reprocess_batch_logs_skipped_records(self, program, user: User, force_migrated_records) -> None:
        """Test reprocess_batch logs when records are skipped (removed=True)."""
        from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, CountryIndividualFactory

        hh = CountryHouseholdFactory(
            batch__program=program,
            batch__country_office=program.country_office,
            removed=False,
        )
        batch = hh.batch

        # Create removed records
        CountryHouseholdFactory(batch=batch, removed=True)
        CountryIndividualFactory(batch=batch, removed=True)

        job = AsyncJobFactory(
            program=program,
            batch=batch,
            owner=user,
            config={"batch_id": batch.pk},
        )

        with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
            with patch("country_workspace.workspaces.admin.batch_reprocessing.logger") as mock_logger:
                result = reprocess_batch(job)

                # Verify skipped records are counted
                assert result.get("skipped_households", 0) == 1
                assert result["skipped_individuals"] == 1

                # Verify logging was called
                mock_logger.info.assert_any_call(
                    "Skipping %d household(s) and %d individual(s) already pushed to HOPE (removed=True) in batch %s",
                    1,
                    1,
                    batch.name,
                )
