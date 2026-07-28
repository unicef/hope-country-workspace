import pytest

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.models import Batch, Household, Individual, User
from country_workspace.utils.import_flow.collector_identity import compute_collector_hash
from country_workspace.workspaces.admin.batch.reprocessing import (
    _apply_import_processor,
    _build_processor,
    _preserve_flex_fields,
    _process_records,
    _resolve_config_object,
    _run_import_processors,
    _sync_household_refs,
    _sync_kobo_household_refs,
    _sync_rdi_household_refs,
    apply_batch_transformers,
    reprocess_batch,
)
from country_workspace.workspaces.models import CountryBatch


pytestmark = pytest.mark.django_db


# --- config/object resolution ----------------------------------------------------


@pytest.mark.parametrize(
    ("object_id", "found", "expected_error"),
    [
        (None, False, None),
        (123, True, None),
        (123, False, "Household mapping 123 is not available for this batch"),
    ],
)
def test_resolve_config_object(mocker, object_id: int | None, found: bool, expected_error: str | None) -> None:
    queryset = mocker.MagicMock()
    obj = mocker.MagicMock(name="config_object") if found else None
    queryset.filter.return_value.first.return_value = obj

    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            _resolve_config_object(queryset, object_id, "Household mapping")
        queryset.filter.assert_called_once_with(pk=object_id)
        queryset.filter.return_value.first.assert_called_once_with()
        return

    assert _resolve_config_object(queryset, object_id, "Household mapping") == (
        (object_id, obj) if object_id else (None, None)
    )

    if object_id is None:
        queryset.filter.assert_not_called()
    else:
        queryset.filter.assert_called_once_with(pk=object_id)
        queryset.filter.return_value.first.assert_called_once_with()


# --- processor builders ----------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "model", "builder_name", "mapping_id"),
    [
        (Batch.BatchSource.KOBO, Household, "build_kobo_household_processor", 11),
        (Batch.BatchSource.KOBO, Individual, "build_kobo_individual_processor", 12),
        (Batch.BatchSource.AURORA, Household, "build_aurora_household_processor", 21),
        (Batch.BatchSource.AURORA, Individual, "build_aurora_individual_processor", 22),
    ],
)
def test_build_processor_uses_source_specific_builders(
    program,
    batch: CountryBatch,
    mocker,
    source,
    model,
    builder_name: str,
    mapping_id: int,
) -> None:
    batch.source = source

    processor = mocker.MagicMock(name="processor")
    builder = mocker.patch(
        f"country_workspace.workspaces.admin.batch.reprocessing.{builder_name}",
        return_value=processor,
    )

    assert _build_processor(batch=batch, program=program, model=model, mapping_id=mapping_id) is processor
    builder.assert_called_once_with(program, mapping_id)


def test_build_processor_uses_default_builder(program, batch: CountryBatch, mocker) -> None:
    processor = mocker.MagicMock(name="processor")
    build_import_processor = mocker.patch(
        "country_workspace.workspaces.admin.batch.reprocessing.build_import_processor",
        return_value=processor,
    )

    assert _build_processor(batch=batch, program=program, model=Household, mapping_id=7) is processor

    build_import_processor.assert_called_once_with(
        program=program,
        model=Household,
        mapping_id=7,
        source=batch.source,
    )


# --- preserve/apply/process helpers ---------------------------------------------


@pytest.mark.parametrize(
    ("source", "model", "expected_preserved"),
    [
        (
            Batch.BatchSource.KOBO,
            Household,
            {
                "household_id": "_preserved_flex_field_0",
                "primary_collector_id": "_preserved_flex_field_1",
                "alternate_collector_id": "_preserved_flex_field_2",
            },
        ),
        (Batch.BatchSource.KOBO, Individual, None),
        (Batch.BatchSource.RDI, Household, None),
    ],
)
def test_preserve_flex_fields(
    batch: CountryBatch,
    mocker,
    source,
    model,
    expected_preserved: dict[str, str] | None,
) -> None:
    batch.source = source
    records = mocker.MagicMock()

    key_transform = mocker.patch(
        "country_workspace.workspaces.admin.batch.reprocessing.KeyTransform",
        side_effect=lambda field, source: f"{source}.{field}",
    )

    annotated, preserved = _preserve_flex_fields(records, batch, model)

    assert preserved == expected_preserved

    if expected_preserved is None:
        assert annotated is records
        records.annotate.assert_not_called()
        key_transform.assert_not_called()
        return

    assert annotated is records.annotate.return_value
    assert key_transform.call_args_list == [mocker.call(field, "flex_fields") for field in expected_preserved]
    records.annotate.assert_called_once_with(
        **{attr: f"flex_fields.{field}" for field, attr in expected_preserved.items()}
    )


def test_apply_import_processor_skips_records_without_raw_data(mocker) -> None:
    record = mocker.MagicMock(raw_data={})
    processor = mocker.MagicMock()

    assert _apply_import_processor(record, processor) is False

    processor.assert_not_called()
    record.save.assert_not_called()


def test_apply_import_processor_updates_record_and_preserves_generated_fields(mocker) -> None:
    record = mocker.MagicMock(raw_data={"external": "value"})
    record._preserved_flex_field_0 = 123
    record.apply_flex_payload.return_value = {"flex_fields", "flex_files"}
    processor = mocker.MagicMock(return_value={"mapped": "value"})

    assert _apply_import_processor(record, processor, {"household_id": "_preserved_flex_field_0"}) is True

    record.apply_flex_payload.assert_called_once_with(
        {"mapped": "value", "household_id": 123},
        preserve_existing_files=True,
    )
    assert record.last_checked is None
    assert record.errors == {}
    record.save.assert_called_once()
    update_fields = record.save.call_args.kwargs["update_fields"]
    assert set(update_fields) == {"flex_fields", "flex_files", "last_checked", "errors"}


def test_apply_import_processor_recomputes_collector_identity_hash(mocker) -> None:
    flex_fields = {"relationship": "NON_BENEFICIARY", "given_name": "John", "birth_date": "1990-01-01"}
    record = mocker.MagicMock(spec=Individual, raw_data={"external": "value"}, flex_fields=dict(flex_fields))
    processor = mocker.MagicMock(return_value={**flex_fields, "phone_no": "123"})

    assert _apply_import_processor(record, processor) is True

    assert record.identity_hash == compute_collector_hash({**flex_fields, "phone_no": "123"})
    record.save.assert_called_once_with(update_fields=["flex_fields", "last_checked", "errors", "identity_hash"])


def test_apply_import_processor_blocks_structural_changes_for_external_collector(mocker) -> None:
    record = mocker.MagicMock(
        spec=Individual,
        raw_data={"external": "value"},
        flex_fields={"relationship": "NON_BENEFICIARY", "role": "PRIMARY", "given_name": "John"},
    )
    processor = mocker.MagicMock(
        return_value={"relationship": "HEAD", "role": "ALTERNATE", "given_name": "John", "phone_no": "1"}
    )

    assert _apply_import_processor(record, processor) is True

    assert record.flex_fields == {
        "relationship": "NON_BENEFICIARY",
        "role": "PRIMARY",
        "given_name": "John",
        "phone_no": "1",
    }


def test_apply_import_processor_blocks_member_to_external_collector(mocker) -> None:
    record = mocker.MagicMock(
        spec=Individual,
        raw_data={"external": "value"},
        flex_fields={"relationship": "HEAD", "role": "PRIMARY"},
    )
    processor = mocker.MagicMock(return_value={"relationship": "NON_BENEFICIARY", "role": "PRIMARY", "given_name": "A"})

    assert _apply_import_processor(record, processor) is True

    assert record.flex_fields == {"relationship": "HEAD", "role": "PRIMARY", "given_name": "A"}


def test_process_records_counts_successfully_processed_records(mocker) -> None:
    records = mocker.MagicMock()
    record_1 = mocker.MagicMock()
    record_2 = mocker.MagicMock()
    record_3 = mocker.MagicMock()
    records.iterator.return_value = iter([record_1, record_2, record_3])

    processor = mocker.MagicMock()
    preserved = {"household_id": "_preserved_flex_field_0"}
    apply_import_processor = mocker.patch(
        "country_workspace.workspaces.admin.batch.reprocessing._apply_import_processor",
        side_effect=[True, False, True],
    )

    assert _process_records(records, processor, preserved) == 2

    records.iterator.assert_called_once_with()
    assert apply_import_processor.call_args_list == [
        mocker.call(record_1, processor, preserved),
        mocker.call(record_2, processor, preserved),
        mocker.call(record_3, processor, preserved),
    ]


def test_run_import_processors_returns_zero_without_records(mocker) -> None:
    records = mocker.MagicMock()
    processor = mocker.MagicMock()
    process_records = mocker.patch("country_workspace.workspaces.admin.batch.reprocessing._process_records")

    result = _run_import_processors(
        label="household",
        records=records,
        count=0,
        mapping=mocker.MagicMock(),
        processor=processor,
        preserved={"household_id": "_preserved_flex_field_0"},
    )

    assert result == 0
    process_records.assert_not_called()


@pytest.mark.parametrize("mapping_name", [None, "Test mapping"])
def test_run_import_processors_processes_records(mocker, mapping_name: str | None) -> None:
    records = mocker.MagicMock()
    processor = mocker.MagicMock()
    preserved = {"household_id": "_preserved_flex_field_0"}
    mapping = None

    if mapping_name is not None:
        mapping = mocker.MagicMock()
        mapping.name = mapping_name

    process_records = mocker.patch(
        "country_workspace.workspaces.admin.batch.reprocessing._process_records",
        return_value=3,
    )

    result = _run_import_processors(
        label="individual",
        records=records,
        count=5,
        mapping=mapping,
        processor=processor,
        preserved=preserved,
    )

    assert result == 3
    process_records.assert_called_once_with(records, processor, preserved)


# --- household refs sync ---------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected_syncer_name"),
    [
        (Batch.BatchSource.KOBO, "_sync_kobo_household_refs"),
        (Batch.BatchSource.RDI, "_sync_rdi_household_refs"),
        (Batch.BatchSource.AURORA, None),
    ],
)
def test_sync_household_refs_dispatches_by_batch_source(
    mocker,
    batch: CountryBatch,
    source,
    expected_syncer_name: str | None,
) -> None:
    batch.source = source
    syncers = {
        "_sync_kobo_household_refs": mocker.patch(
            "country_workspace.workspaces.admin.batch.reprocessing._sync_kobo_household_refs"
        ),
        "_sync_rdi_household_refs": mocker.patch(
            "country_workspace.workspaces.admin.batch.reprocessing._sync_rdi_household_refs"
        ),
    }

    _sync_household_refs(batch)

    for name, syncer in syncers.items():
        if name == expected_syncer_name:
            syncer.assert_called_once_with(batch)
        else:
            syncer.assert_not_called()


def test_sync_rdi_household_refs_uses_only_id_fields(program) -> None:
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    fields = HOUSEHOLD_ROLE_REF_FIELDS
    batch = CountryBatchFactory(program=program, country_office=program.country_office, source=Batch.BatchSource.RDI)
    household = CountryHouseholdFactory(
        batch=batch,
        flex_fields={
            fields.head_of_household: "IND-1",
            fields.primary_collector: "IND-2",
            fields.alternate_collector: "IND-3",
            "head_of_household": "LEGACY-HEAD",
            "primary_collector": "LEGACY-PRIMARY",
            "alternate_collector": "LEGACY-ALT",
        },
    )
    head = CountryIndividualFactory(batch=batch, household=household, flex_fields={"individual_id": "IND-1"})
    primary = CountryIndividualFactory(batch=batch, household=household, flex_fields={"individual_id": "IND-2"})
    alternate = CountryIndividualFactory(batch=batch, household=household, flex_fields={"individual_id": "IND-3"})

    _sync_rdi_household_refs(batch)

    household.refresh_from_db()
    assert household.flex_fields[fields.head_of_household] == head.pk
    assert household.flex_fields[fields.primary_collector] == primary.pk
    assert household.flex_fields[fields.alternate_collector] == alternate.pk
    assert household.flex_fields["head_of_household"] == "LEGACY-HEAD"


def test_sync_kobo_household_refs_resolves_first_matching_members(program) -> None:
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    fields = HOUSEHOLD_ROLE_REF_FIELDS
    batch = CountryBatchFactory(program=program, country_office=program.country_office, source=Batch.BatchSource.KOBO)
    household = CountryHouseholdFactory(batch=batch, flex_fields={})

    head = CountryIndividualFactory(batch=batch, household=household, flex_fields={"relationship": "HEAD"})
    primary = CountryIndividualFactory(batch=batch, household=household, flex_fields={"role": "PRIMARY"})
    alternate = CountryIndividualFactory(batch=batch, household=household, flex_fields={"role": "ALTERNATE"})
    CountryIndividualFactory(batch=batch, household=household, flex_fields={"role": "PRIMARY"})

    _sync_kobo_household_refs(batch)

    household.refresh_from_db()
    assert household.flex_fields[fields.head_of_household] == head.pk
    assert household.flex_fields[fields.primary_collector] == primary.pk
    assert household.flex_fields[fields.alternate_collector] == alternate.pk


def test_sync_kobo_household_refs_keeps_preserved_external_collector_refs(program) -> None:
    from testutils.factories import CountryBatchFactory, CountryHouseholdFactory, CountryIndividualFactory

    fields = HOUSEHOLD_ROLE_REF_FIELDS
    batch = CountryBatchFactory(program=program, country_office=program.country_office, source=Batch.BatchSource.KOBO)
    collector = CountryIndividualFactory(
        batch=batch,
        household=None,
        flex_fields={"relationship": "NON_BENEFICIARY", "role": "PRIMARY"},
    )
    household = CountryHouseholdFactory(
        batch=batch,
        flex_fields={
            fields.primary_collector: collector.pk,
            fields.alternate_collector: collector.pk,
        },
    )
    head = CountryIndividualFactory(batch=batch, household=household, flex_fields={"relationship": "HEAD"})

    _sync_kobo_household_refs(batch)

    household.refresh_from_db()
    assert household.flex_fields[fields.head_of_household] == head.pk
    assert household.flex_fields[fields.primary_collector] == collector.pk
    assert household.flex_fields[fields.alternate_collector] == collector.pk


# --- reprocess_batch -------------------------------------------------------------


def test_reprocess_batch_requires_batch_id(user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={})

    with pytest.raises(ValueError, match="batch_id is required"):
        reprocess_batch(job)


def test_reprocess_batch_raises_for_missing_batch(user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={"batch_id": 999999})

    with pytest.raises(Batch.DoesNotExist, match="Batch 999999 not found"):
        reprocess_batch(job)


def test_reprocess_batch_counts_only_active_records(
    batch: CountryBatch,
    job_factory,
    validation_jobs,
    postprocessing,
    mocker,
) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    active_household = CountryHouseholdFactory(batch=batch, raw_data={"size": 1})
    removed_household = CountryHouseholdFactory(batch=batch, raw_data={"size": 2}, removed=True)
    CountryIndividualFactory(batch=batch, household=active_household, raw_data={"full_name": "Active"})
    CountryIndividualFactory(batch=batch, household=removed_household, raw_data={"full_name": "Removed"}, removed=True)

    expected_households = batch.household_set.filter(removed=False).count()
    skipped_households = batch.household_set.filter(removed=True).count()
    expected_individuals = batch.individual_set.filter(removed=False).count()
    skipped_individuals = batch.individual_set.filter(removed=True).count()

    mocker.patch(
        "country_workspace.workspaces.admin.batch.reprocessing._run_import_processors",
        side_effect=[expected_households, expected_individuals],
    )

    result = reprocess_batch(job_factory(batch))

    assert result["households"] == expected_households
    assert result["skipped_households"] == skipped_households
    assert result["individuals"] == expected_individuals
    assert result["skipped_individuals"] == skipped_individuals
    assert result["mapped_households"] == expected_households
    assert result["mapped_individuals"] == expected_individuals

    postprocessing.assert_called_once()
    validation_jobs.assert_called_once()


def test_reprocess_batch_passes_transformers_to_postprocessing(
    batch: CountryBatch,
    job_factory,
    validation_jobs,
    postprocessing,
    mocker,
) -> None:
    from testutils.factories import CountryHouseholdFactory, TransformerFactory

    CountryHouseholdFactory(batch=batch, raw_data={"size": 1})
    household_transformer = TransformerFactory(office=batch.country_office)
    individual_transformer = TransformerFactory(office=batch.country_office)

    mocker.patch("country_workspace.workspaces.admin.batch.reprocessing._run_import_processors", return_value=1)

    reprocess_batch(
        job_factory(
            batch,
            household_transformer_id=household_transformer.pk,
            individual_transformer_id=individual_transformer.pk,
        )
    )

    postprocessing.assert_called_once()
    assert postprocessing.call_args.kwargs["household_transformer_id"] == household_transformer.pk
    assert postprocessing.call_args.kwargs["individual_transformer_id"] == individual_transformer.pk
    assert postprocessing.call_args.kwargs["sync_household_refs"].__name__ == "_sync_household_refs"


def test_reprocess_batch_creates_validation_jobs_for_people_only_batch(
    people_program,
    job_factory,
    validation_jobs,
    postprocessing,
    mocker,
) -> None:
    from testutils.factories import CountryBatchFactory, CountryIndividualFactory

    batch = CountryBatchFactory(
        program=people_program,
        country_office=people_program.country_office,
        source=Batch.BatchSource.RDI,
    )
    CountryIndividualFactory(batch=batch, household=None, raw_data={"full_name": "Person"})

    job = job_factory(batch)
    processor = mocker.MagicMock()
    mocker.patch("country_workspace.workspaces.admin.batch.reprocessing._build_processor", return_value=processor)
    mocker.patch("country_workspace.workspaces.admin.batch.reprocessing._run_import_processors", return_value=1)

    reprocess_batch(job)

    validation_jobs.assert_called_once()
    assert validation_jobs.call_args.kwargs["description"] == f"Validate records for batch {batch.pk}"
    assert validation_jobs.call_args.kwargs["owner"] == job.owner
    assert validation_jobs.call_args.kwargs["program"] == batch.program
    assert list(validation_jobs.call_args.kwargs["queryset"]) == list(batch.individual_set.filter(removed=False))

    postprocessing.assert_called_once()


# --- apply_batch_transformers ----------------------------------------------------


def test_apply_batch_transformers_requires_batch_id(user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={})

    with pytest.raises(ValueError, match="batch_id is required"):
        apply_batch_transformers(job)


def test_apply_batch_transformers_requires_transformer_ids(batch: CountryBatch, user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, batch=batch, program=batch.program, config={"batch_id": batch.pk})

    with pytest.raises(ValueError, match="At least one transformer id is required"):
        apply_batch_transformers(job)


def test_apply_batch_transformers_raises_for_missing_transformer(batch: CountryBatch, user: User) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(
        owner=user,
        batch=batch,
        program=batch.program,
        config={"batch_id": batch.pk, "individual_transformer_id": 999999},
    )

    with pytest.raises(ValueError, match="Individual transformer 999999 is not available for this batch"):
        apply_batch_transformers(job)


def test_apply_batch_transformers_delegates_to_transformations_utility(
    batch: CountryBatch,
    user: User,
    mocker,
) -> None:
    from testutils.factories import AsyncJobFactory, TransformerFactory

    household_transformer = TransformerFactory(office=batch.country_office)
    individual_transformer = TransformerFactory(office=batch.country_office)
    job = AsyncJobFactory(
        owner=user,
        batch=batch,
        program=batch.program,
        config={
            "batch_id": batch.pk,
            "household_transformer_id": household_transformer.pk,
            "individual_transformer_id": individual_transformer.pk,
        },
    )

    apply_transformers = mocker.patch(
        "country_workspace.workspaces.admin.batch.reprocessing.apply_transformers_to_batch",
        return_value={"transformed_households": 3, "transformed_individuals": 7},
    )

    response = apply_batch_transformers(job)

    apply_transformers.assert_called_once_with(
        batch,
        household_transformer_id=household_transformer.pk,
        individual_transformer_id=individual_transformer.pk,
    )
    assert response["batch_id"] == batch.pk
    assert response["batch_name"] == batch.name
    assert response["transformed_individuals"] == 7
    if batch.program.is_master_detail:
        assert response["transformed_households"] == 3
