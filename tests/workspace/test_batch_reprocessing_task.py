from unittest.mock import Mock, patch

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


def test_reprocess_batch_missing_config(user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={})

    with pytest.raises(ValueError, match="batch_id is required"):
        reprocess_batch(job)


def test_reprocess_batch_invalid_batch_id(user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={"batch_id": 99999})

    with pytest.raises(Batch.DoesNotExist, match="Batch 99999 not found"):
        reprocess_batch(job)


def test_reprocess_empty_batch(program, user: User) -> None:
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


def test_reprocess_batch_with_households(program, user: User, force_migrated_records) -> None:
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
        is_master_detail = batch.program.is_master_detail
        if is_master_detail:
            assert households_count == 1
        assert result["individuals"] == batch.individual_set.filter(removed=False).count()
        mock_create.assert_called_once()


def test_reprocess_batch_with_individuals_only(program, user: User, force_migrated_records) -> None:
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
        if batch.program.is_master_detail:
            assert result["households"] == 0
        assert result["individuals"] == 1
        mock_create.assert_called_once()

def test_build_processor_uses_kobo_builders(program, user: User) -> None:
    from testutils.factories import CountryBatchFactory
    from country_workspace.workspaces.admin.batch_reprocessing import _build_processor
    from country_workspace.models import Household, Individual

    batch = CountryBatchFactory(
        program=program, country_office=program.country_office, source=Batch.BatchSource.KOBO
    )

    with (
        patch(
            "country_workspace.workspaces.admin.batch_reprocessing.build_kobo_household_processor",
            return_value=Mock(name="kobo_hh"),
        ) as build_hh,
        patch(
            "country_workspace.workspaces.admin.batch_reprocessing.build_kobo_individual_processor",
            return_value=Mock(name="kobo_ind"),
        ) as build_ind,
    ):
        assert (
            _build_processor(
                batch=batch,
                program=program,
                model=Household,
                mapping_id=1,
                transformer_id=2,
            )
            is build_hh.return_value
        )
        assert (
            _build_processor(
                batch=batch,
                program=program,
                model=Individual,
                mapping_id=3,
                transformer_id=4,
            )
            is build_ind.return_value
        )

    build_hh.assert_called_once_with(program, 1, 2)
    build_ind.assert_called_once_with(program, 3, 4)

def test_build_processor_uses_aurora_builders(program, user: User) -> None:
    from testutils.factories import CountryBatchFactory
    from country_workspace.workspaces.admin.batch_reprocessing import _build_processor
    from country_workspace.models import Household, Individual

    batch = CountryBatchFactory(
        program=program, country_office=program.country_office, source=Batch.BatchSource.AURORA
    )

    with (
        patch(
            "country_workspace.workspaces.admin.batch_reprocessing.build_aurora_household_processor",
            return_value=Mock(name="aurora_hh"),
        ) as build_hh,
        patch(
            "country_workspace.workspaces.admin.batch_reprocessing.build_aurora_individual_processor",
            return_value=Mock(name="aurora_ind"),
        ) as build_ind,
    ):
        assert (
            _build_processor(
                batch=batch,
                program=program,
                model=Household,
                mapping_id=5,
                transformer_id=6,
            )
            is build_hh.return_value
        )
        assert (
            _build_processor(
                batch=batch,
                program=program,
                model=Individual,
                mapping_id=7,
                transformer_id=8,
            )
            is build_ind.return_value
        )

    build_hh.assert_called_once_with(program, 5, 6)
    build_ind.assert_called_once_with(program, 7, 8)

def test_build_processor_uses_default_builder(program, user: User) -> None:
    from testutils.factories import CountryBatchFactory
    from country_workspace.workspaces.admin.batch_reprocessing import _build_processor
    from country_workspace.models import Household

    batch = CountryBatchFactory(
        program=program, country_office=program.country_office, source=Batch.BatchSource.RDI
    )

    with patch(
        "country_workspace.workspaces.admin.batch_reprocessing.build_import_processor",
        return_value=Mock(name="default_processor"),
    ) as build_default:
        result = _build_processor(
            batch=batch,
            program=program,
            model=Household,
            mapping_id=9,
            transformer_id=10,
        )

    assert result is build_default.return_value
    build_default.assert_called_once_with(
        program=program,
        model=Household,
        mapping_id=9,
        transformer_id=10,
        source=batch.source,
    )


def test_reprocess_batch_with_mixed_content(program, user: User, force_migrated_records) -> None:
    from testutils.factories import (
        AsyncJobFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
    )

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 3},
    )
    batch = hh.batch

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
        is_master_detail = batch.program.is_master_detail
        if is_master_detail:
            assert households_count == 1
        assert result["individuals"] == batch.individual_set.filter(removed=False).count()
        mock_create.assert_called_once()


def test_reprocess_batch_multiple_households(program, user: User, force_migrated_records) -> None:
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

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
        is_master_detail = batch.program.is_master_detail
        if is_master_detail:
            assert result.get("households", 0) == 2
        assert result["individuals"] == batch.individual_set.filter(removed=False).count()
        mock_create.assert_called_once()


def test_reprocess_batch_queryset_prefetching(program, user: User, force_migrated_records) -> None:
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 2},
    )
    batch = hh.batch

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

        is_master_detail = batch.program.is_master_detail
        calls = [c.kwargs for c in mock_create.call_args_list]
        if is_master_detail:
            hh_call = next(c for c in calls if c.get("description", "").endswith(" - Households"))
            queryset = hh_call["queryset"]
            assert "members" in getattr(queryset, "_prefetch_related_lookups", ())


def test_reprocess_batch_result_structure(program, user: User, force_migrated_records) -> None:
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

        assert "batch_id" in result
        assert "batch_name" in result
        assert "individuals" in result

        assert isinstance(result["batch_id"], int)
        assert isinstance(result["batch_name"], str)
        assert isinstance(result["individuals"], int)

        # Households key is only present when master_detail is True
        if batch.program.is_master_detail:
            assert "households" in result
            assert isinstance(result["households"], int)


def test_reprocess_batch_household_mapping_not_found(program, user: User, force_migrated_records) -> None:
    """Test reprocess_batch handles MappingImporter.DoesNotExist for household mapping."""
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"col1": "value1"},
    )
    batch = hh.batch

    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    batch.program.beneficiary_group = bg
    batch.program.save()

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={"batch_id": batch.pk, "household_mapping_id": 99999},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_households", 0) == 1


def test_reprocess_batch_individual_mapping_not_found(program, user: User, force_migrated_records) -> None:
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
        config={"batch_id": batch.pk, "individual_mapping_id": 99999},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_individuals", 0) == 1

def test_apply_transformations_no_raw_data(program, user: User) -> None:
    """Test _apply_transformations returns False when record has no raw_data."""
    from country_workspace.workspaces.admin.batch_reprocessing import _apply_transformations
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
    )
    hh.raw_data = {}
    hh.save(update_fields=["raw_data"])

    result = _apply_transformations(hh, lambda data: data)

    assert result is False
    hh.refresh_from_db()
    assert hh.flex_fields != {"field1": "value1"}

def test_apply_transformations_successful(program, user: User) -> None:
    """Test _apply_transformations with only mapping (no transformer)."""
    from country_workspace.workspaces.admin.batch_reprocessing import _apply_transformations
    from country_workspace.models import Batch, Household
    from country_workspace.utils.import_processing import build_import_processor
    from testutils.factories import CountryHouseholdFactory, MappingImporterFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"old_col": "value1", "other_col": "value2"},
        flex_fields={"existing": "data"},
    )

    mapping = MappingImporterFactory(rules="old_col=new_col")

    processor = build_import_processor(
        program=program,
        model=Household,
        mapping_id=mapping.pk,
        source=Batch.BatchSource.RDI,
    )
    result = _apply_transformations(hh, processor)

    assert result is True
    hh.refresh_from_db()
    assert hh.flex_fields["new_col"] == "value1"
    assert "old_col" not in hh.flex_fields
    assert hh.flex_fields["other_col"] == "value2"
    assert hh.last_checked is None
    assert hh.errors == {}

def test_apply_transformations_with_mapping_then_transformer(program, user: User) -> None:
    """Test _apply_transformations with mapping first, then transformer - correct flow."""
    from country_workspace.workspaces.admin.batch_reprocessing import _apply_transformations
    from country_workspace.models import Batch, Household
    from country_workspace.utils.import_processing import build_import_processor
    from testutils.factories import CountryHouseholdFactory, MappingImporterFactory, TransformerFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"gender": "M", "age": 25},
        flex_fields={"existing": "data"},
    )

    mapping = MappingImporterFactory(rules="gender=sex")
    transformer = TransformerFactory(
        value_transformations="function t(d) { if(d['sex']=='M') d['sex']='MALE'; return d; }"
    )

    processor = build_import_processor(
        program=program,
        model=Household,
        mapping_id=mapping.pk,
        transformer_id=transformer.pk,
        source=Batch.BatchSource.RDI,
    )
    result = _apply_transformations(hh, processor)

    assert result is True
    hh.refresh_from_db()
    assert hh.flex_fields["sex"] == "MALE"
    assert hh.flex_fields["age"] == 25
    assert "gender" not in hh.flex_fields
    assert hh.errors == {}

def test_apply_transformations_with_transformer_only(program, user: User) -> None:
    """Test _apply_transformations with only transformer (no mapping)."""
    from country_workspace.workspaces.admin.batch_reprocessing import _apply_transformations
    from country_workspace.models import Batch, Household
    from country_workspace.utils.import_processing import build_import_processor
    from testutils.factories import CountryHouseholdFactory, TransformerFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"gender": "M", "status": "1"},
        flex_fields={"existing": "data"},
    )

    transformer = TransformerFactory(
        value_transformations="function t(d) { if(d['gender']=='M') d['gender']='MALE'; if(d['status']=='1') d['status']='ACTIVE'; return d; }",  # noqa: E501
    )

    processor = build_import_processor(
        program=program,
        model=Household,
        mapping_id=0,
        transformer_id=transformer.pk,
        source=Batch.BatchSource.RDI,
    )
    result = _apply_transformations(hh, processor)

    assert result is True
    hh.refresh_from_db()
    assert hh.flex_fields["gender"] == "MALE"
    assert hh.flex_fields["status"] == "ACTIVE"
    assert hh.errors == {}

def test_apply_transformations_with_neither_transformer_nor_mapping(program, user: User) -> None:
    """Test _apply_transformations with neither transformer nor mapping (both None)."""
    from country_workspace.workspaces.admin.batch_reprocessing import _apply_transformations
    from country_workspace.models import Batch, Household
    from country_workspace.utils.import_processing import build_import_processor
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"field1": "value1", "field2": "value2"},
        flex_fields={"existing": "data"},
    )

    processor = build_import_processor(
        program=program,
        model=Household,
        mapping_id=0,
        transformer_id=None,
        source=Batch.BatchSource.RDI,
    )
    result = _apply_transformations(hh, processor)

    assert result is True
    hh.refresh_from_db()
    assert hh.flex_fields["field1"] == "value1"
    assert hh.flex_fields["field2"] == "value2"
    assert hh.errors == {}


def test_reprocess_batch_household_mapping_applied(program, user: User, force_migrated_records) -> None:
    """Test reprocess_batch applies household mapping when all conditions are met."""
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, MappingImporterFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    program.beneficiary_group = bg
    program.save()

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"external_field": "external_value", "other_field": "other_value"},
        flex_fields={"existing": "data"},
    )
    batch = hh.batch

    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="external_field=mapped_field",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={"batch_id": batch.pk, "household_mapping_id": household_mapping.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_households", 0) == 1
        assert result.get("households", 0) == 1

        hh.refresh_from_db()
        assert hh.flex_fields["mapped_field"] == "external_value"


def test_reprocess_batch_household_mapping_then_transformer_applied(
    program, user: User, force_migrated_records
) -> None:
    """Test reprocess_batch applies mapping first, then transformer - correct flow."""
    from testutils.factories import (
        AsyncJobFactory,
        CountryHouseholdFactory,
        MappingImporterFactory,
        TransformerFactory,
    )
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    program.beneficiary_group = bg
    program.save()

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"gender": "M", "age": 25},
        flex_fields={"existing": "data"},
    )
    batch = hh.batch

    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="gender=sex",
    )
    household_transformer = TransformerFactory(
        office=program.country_office,
        value_transformations="function t(d) { if(d['sex']=='M') d['sex']='MALE'; return d; }",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={
            "batch_id": batch.pk,
            "household_transformer_id": household_transformer.pk,
            "household_mapping_id": household_mapping.pk,
        },
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_households", 0) == 1
        assert result.get("households", 0) == 1

        hh.refresh_from_db()
        assert hh.flex_fields["sex"] == "MALE"
        assert hh.flex_fields["age"] == 25
        assert "gender" not in hh.flex_fields


def test_reprocess_batch_individual_mapping_then_transformer_applied(
    program, user: User, force_migrated_records
) -> None:
    """Test reprocess_batch applies mapping first, then transformer for individuals."""
    from testutils.factories import (
        AsyncJobFactory,
        CountryBatchFactory,
        CountryIndividualFactory,
        MappingImporterFactory,
        TransformerFactory,
    )

    batch = CountryBatchFactory(program=program, country_office=program.country_office)

    ind = CountryIndividualFactory(
        batch=batch,
        household=None,
        raw_data={"gender": "F", "status": "1"},
        flex_fields={"existing": "data"},
    )

    individual_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.individual_checker,
        rules="gender=sex",
    )
    individual_transformer = TransformerFactory(
        office=program.country_office,
        value_transformations="function t(d) { if(d['sex']=='F') d['sex']='FEMALE'; if(d['status']=='1') d['status']='ACTIVE'; return d; }",  # noqa: E501
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={
            "batch_id": batch.pk,
            "individual_transformer_id": individual_transformer.pk,
            "individual_mapping_id": individual_mapping.pk,
        },
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_individuals", 0) == 1
        assert result.get("individuals", 0) == 1

        ind.refresh_from_db()
        assert ind.flex_fields["sex"] == "FEMALE"
        assert ind.flex_fields["status"] == "ACTIVE"
        assert "gender" not in ind.flex_fields


def test_reprocess_batch_transformer_not_found(program, user: User, force_migrated_records) -> None:
    """Test reprocess_batch handles Transformer.DoesNotExist gracefully."""
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, MappingImporterFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    program.beneficiary_group = bg
    program.save()

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"field1": "value1"},
    )
    batch = hh.batch

    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="field1=field2",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={
            "batch_id": batch.pk,
            "household_transformer_id": 99999,
            "household_mapping_id": household_mapping.pk,
        },
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_households", 0) == 1

        hh.refresh_from_db()
        assert hh.flex_fields["field2"] == "value1"


def test_reprocess_batch_individual_transformer_not_found(program, user: User, force_migrated_records, caplog) -> None:
    """Test reprocess_batch handles Transformer.DoesNotExist for individual transformer gracefully."""
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory, MappingImporterFactory

    ind = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"col1": "value1"},
    )
    batch = ind.batch

    individual_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.individual_checker,
        rules="col1=col2",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={
            "batch_id": batch.pk,
            "individual_transformer_id": 99999,
            "individual_mapping_id": individual_mapping.pk,
        },
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        with caplog.at_level("WARNING"):
            result = reprocess_batch(job)

            assert result["batch_id"] == batch.pk
            assert result.get("mapped_individuals", 0) == 1

            ind.refresh_from_db()
            assert ind.flex_fields["col2"] == "value1"

            assert any(
                "Individual transformer 99999 not found, skipping transformer" in record.message
                for record in caplog.records
                if record.levelname == "WARNING"
            )


def test_reprocess_batch_household_transformer_only(program, user: User, force_migrated_records) -> None:
    """Test reprocess_batch with only household transformer (no mapping)."""
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, TransformerFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    program.beneficiary_group = bg
    program.save()

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"gender": "M", "status": "1"},
        flex_fields={"existing": "data"},
    )
    batch = hh.batch

    household_transformer = TransformerFactory(
        office=program.country_office,
        value_transformations="function t(d) { if(d['gender']=='M') d['gender']='MALE'; if(d['status']=='1') d['status']='ACTIVE'; return d; }",  # noqa: E501
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={
            "batch_id": batch.pk,
            "household_transformer_id": household_transformer.pk,
        },
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_households", 0) == 1

        hh.refresh_from_db()
        assert hh.flex_fields["gender"] == "MALE"
        assert hh.flex_fields["status"] == "ACTIVE"


def test_reprocess_batch_individual_transformer_only(program, user: User, force_migrated_records) -> None:
    """Test reprocess_batch with only individual transformer (no mapping)."""
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory, TransformerFactory

    ind = CountryIndividualFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"gender": "F"},
        flex_fields={"existing": "data"},
    )
    batch = ind.batch

    individual_transformer = TransformerFactory(
        office=program.country_office,
        value_transformations="function t(d) { if(d['gender']=='F') d['gender']='FEMALE'; return d; }",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={
            "batch_id": batch.pk,
            "individual_transformer_id": individual_transformer.pk,
        },
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_individuals", 0) == 1

        ind.refresh_from_db()
        assert ind.flex_fields["gender"] == "FEMALE"


def test_reprocess_batch_individual_mapping_applied(program, user: User, force_migrated_records) -> None:
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory, MappingImporterFactory

    ind = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"external_col": "external_val", "another_col": "another_val"},
        flex_fields={"existing": "data"},
    )
    batch = ind.batch

    individual_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.individual_checker,
        rules="external_col=mapped_col",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={"batch_id": batch.pk, "individual_mapping_id": individual_mapping.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert result.get("mapped_individuals", 0) == 1
        assert result["individuals"] == 1

        ind.refresh_from_db()
        assert ind.flex_fields["mapped_col"] == "external_val"
        assert "external_col" not in ind.flex_fields
        assert ind.flex_fields["another_col"] == "another_val"


def test_reprocess_batch_household_mapping_not_applied_when_no_households(program, user: User) -> None:
    from testutils.factories import AsyncJobFactory, MappingImporterFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    program.beneficiary_group = bg
    program.save()

    from testutils.factories import CountryBatchFactory

    empty_batch = CountryBatchFactory(program=program, country_office=program.country_office)

    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="external_field=mapped_field",
    )

    job = AsyncJobFactory(
        program=program,
        batch=empty_batch,
        owner=user,
        config={"batch_id": empty_batch.pk, "household_mapping_id": household_mapping.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == empty_batch.pk
        assert result.get("mapped_households", 0) == 0
        assert result.get("households", 0) == 0


def test_reprocess_batch_household_mapping_not_applied_when_not_master_detail(
    program, user: User, force_migrated_records
) -> None:
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, MappingImporterFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=False)
    program.beneficiary_group = bg
    program.save()

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        raw_data={"external_field": "external_value"},
    )
    batch = hh.batch

    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="external_field=mapped_field",
    )

    job = AsyncJobFactory(
        program=program,
        batch=batch,
        owner=user,
        config={"batch_id": batch.pk, "household_mapping_id": household_mapping.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == batch.pk
        assert "mapped_households" not in result
        hh.refresh_from_db()
        assert "mapped_field" not in hh.flex_fields


def test_reprocess_batch_individual_mapping_not_applied_when_no_individuals(program, user: User) -> None:
    from testutils.factories import AsyncJobFactory, MappingImporterFactory
    from testutils.factories import CountryBatchFactory

    empty_batch = CountryBatchFactory(program=program, country_office=program.country_office)

    individual_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.individual_checker,
        rules="external_col=mapped_col",
    )

    job = AsyncJobFactory(
        program=program,
        batch=empty_batch,
        owner=user,
        config={"batch_id": empty_batch.pk, "individual_mapping_id": individual_mapping.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result["batch_id"] == empty_batch.pk
        assert result.get("mapped_individuals", 0) == 0
        assert result["individuals"] == 0


def test_reprocess_batch_logs_skipped_records(program, user: User, force_migrated_records) -> None:
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, CountryIndividualFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    program.beneficiary_group = bg
    program.save()

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        removed=False,
    )
    batch = hh.batch

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

            assert result.get("skipped_households", 0) == 1
            assert result["skipped_individuals"] == 0

            mock_logger.info.assert_any_call(
                "Skipping %d household(s) and %d individual(s) already pushed to HOPE (removed=True) in batch %s",
                1,
                0,
                batch.name,
            )
