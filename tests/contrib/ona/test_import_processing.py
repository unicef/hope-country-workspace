from datetime import datetime, timedelta, timezone
from unittest.mock import ANY

import pytest
from pytest_mock import MockerFixture

from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.utils.flex_files import FlexFileContent, pending_marker

from country_workspace.contrib.ona.import_processing import (
    Config,
    ImportResult,
    create_household,
    create_individual,
    get_ona_originating_id,
    get_ona_submission_cursor_id,
    import_data,
    import_submission,
    _validation_queryset,
)


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": "ONA batch",
        "validate_after_import": False,
        "form_id": "9153",
        "master_detail": False,
    }


@pytest.fixture
def job(mocker: MockerFixture, config: Config):
    job = mocker.MagicMock()
    job.config = config
    job.batch_id = None
    job.program.country_office = mocker.MagicMock()
    job.owner = mocker.MagicMock()
    return job


@pytest.fixture(autouse=True)
def ona_constance_config(mocker: MockerFixture):
    constance_config = mocker.patch("country_workspace.contrib.ona.import_processing.constance_config")
    constance_config.ONA_API_URL = "https://data.inform.unicef.org"
    constance_config.ONA_API_TOKEN = "dummy-token"
    constance_config.ONA_IMPORT_TIMEBOX_MINUTES = 0
    return constance_config


@pytest.fixture(autouse=True)
def ona_sync_log(mocker: MockerFixture):
    program_ct = mocker.MagicMock(name="program_ct")
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.ContentType.objects.get_for_model",
        return_value=program_ct,
    )
    filter_mock = mocker.patch("country_workspace.contrib.ona.import_processing.SyncLog.objects.filter")
    filter_mock.return_value.first.return_value = None
    update_or_create_mock = mocker.patch(
        "country_workspace.contrib.ona.import_processing.SyncLog.objects.update_or_create",
    )
    return {
        "program_ct": program_ct,
        "filter": filter_mock,
        "update_or_create": update_or_create_mock,
    }


@pytest.fixture(autouse=True)
def ona_data_imported_signal(mocker: MockerFixture):
    return mocker.patch("country_workspace.contrib.ona.import_processing.data_imported_signal.send")


@pytest.fixture(autouse=True)
def ona_import_lock(mocker: MockerFixture):
    return mocker.patch("country_workspace.contrib.ona.import_processing.cache.lock")


def _mock_atomic(mocker: MockerFixture) -> None:
    atomic = mocker.patch("country_workspace.contrib.ona.import_processing.transaction.atomic")
    atomic.return_value.__enter__.return_value = None
    atomic.return_value.__exit__.return_value = None


def test_get_ona_originating_id_prefers_uuid() -> None:
    assert get_ona_originating_id({"_uuid": "uuid-123", "_id": 999}) == "ONA#uuid-123"


def test_get_ona_originating_id_falls_back_to_id() -> None:
    assert get_ona_originating_id({"_id": 999}) == "ONA#999"


def test_get_ona_originating_id_raises_when_missing_identifier() -> None:
    with pytest.raises(ImportError, match="ONA submission is missing"):
        get_ona_originating_id({})


def test_get_ona_submission_cursor_id_prefers_numeric_id() -> None:
    assert get_ona_submission_cursor_id({"_id": "101", "_uuid": "uuid-101"}) == 101
    assert get_ona_submission_cursor_id({"id": 102, "uuid": "uuid-102"}) == 102


def test_get_ona_submission_cursor_id_rejects_uuid_only_submission() -> None:
    with pytest.raises(ImportError, match="numeric _id/id"):
        get_ona_submission_cursor_id({"_uuid": "uuid-only"})


def test_get_ona_submission_cursor_id_rejects_non_numeric_id() -> None:
    with pytest.raises(ImportError, match="must be numeric"):
        get_ona_submission_cursor_id({"_id": "abc"})


def test_import_data_requires_form_id(job, config: Config) -> None:
    job.config = {**config, "form_id": ""}

    with pytest.raises(ImportError, match="form_id is required"):
        import_data(job)


@pytest.mark.parametrize(
    ("program_id", "form_id"),
    [(123, "9153"), (124, "9153"), (123, "9154")],
)
def test_import_data_locks_by_program_and_form(
    mocker: MockerFixture,
    job,
    config: Config,
    ona_import_lock,
    program_id: int,
    form_id: str,
) -> None:
    _mock_atomic(mocker)
    job.program.id = program_id
    job.config = {**config, "form_id": form_id}

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch = batch_cls.objects.create.return_value
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")

    lock = ona_import_lock.return_value

    def check_locked(*args, **kwargs):
        lock.__enter__.assert_called_once()
        lock.__exit__.assert_not_called()
        return ImportResult(people=0)

    import_mock = mocker.patch(
        "country_workspace.contrib.ona.import_processing.import_submissions",
        side_effect=check_locked,
    )

    result = import_data(job)

    assert result == ImportResult(people=0)
    ona_import_lock.assert_called_once_with(
        f"lock:ona-import:{program_id}:{form_id}",
        60,
        auto_renewal=True,
    )
    lock.__exit__.assert_called_once()
    import_mock.assert_called_once_with(
        batch,
        client_cls.return_value,
        job.config,
        job=job,
        timebox_seconds=None,
    )


@pytest.mark.parametrize(
    ("master_detail", "imported_results", "expected"),
    [
        pytest.param(
            False,
            [ImportResult(people=1), ImportResult(people=2)],
            ImportResult(people=3),
            id="people_only",
        ),
        pytest.param(
            True,
            [ImportResult(people=1, households=1), ImportResult(people=2, households=3)],
            ImportResult(people=3, households=4),
            id="master_detail",
        ),
    ],
)
def test_import_data_calls_client_and_aggregates(
    mocker: MockerFixture,
    job,
    config: Config,
    master_detail: bool,
    imported_results: list[ImportResult],
    expected: ImportResult,
) -> None:
    _mock_atomic(mocker)
    job.config = {**config, "master_detail": master_detail}

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = [
        {"_id": 1, "_uuid": "uuid-1"},
        {"_id": 2, "_uuid": "uuid-2"},
    ]

    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    import_submission_mock = mocker.patch("country_workspace.contrib.ona.import_processing.import_submission")
    import_submission_mock.side_effect = imported_results

    result = import_data(job)

    assert result == expected

    client_cls.assert_called_once_with(
        base_url="https://data.inform.unicef.org",
        token="dummy-token",
    )
    client_cls.return_value.iter_submissions.assert_called_once_with(config["form_id"], last_id=None)

    import_submission_mock.assert_any_call(
        batch=batch, submission={"_id": 1, "_uuid": "uuid-1"}, config=job.config, files={}
    )
    import_submission_mock.assert_any_call(
        batch=batch, submission={"_id": 2, "_uuid": "uuid-2"}, config=job.config, files={}
    )

    postprocessing.assert_called_once_with(
        batch,
        household_transformer_id=None,
        individual_transformer_id=None,
    )

    batch_cls.objects.create.assert_called_once()
    batch.save.assert_called_once_with(update_fields=["status"])


def test_import_data_skips_submissions_up_to_synclog_last_id(
    mocker: MockerFixture,
    job,
    config: Config,
    ona_sync_log,
) -> None:
    _mock_atomic(mocker)
    sync_log = mocker.MagicMock()
    sync_log.last_id = "100"
    ona_sync_log["filter"].return_value.first.return_value = sync_log

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = [
        {"_id": 99, "_uuid": "old-99"},
        {"_id": 100, "_uuid": "old-100"},
        {"_id": 101, "_uuid": "new-101"},
        {"_id": 102, "_uuid": "new-102"},
    ]

    mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    import_submission_mock = mocker.patch("country_workspace.contrib.ona.import_processing.import_submission")
    import_submission_mock.side_effect = [ImportResult(people=1), ImportResult(people=2)]

    result = import_data(job)

    client_cls.return_value.iter_submissions.assert_called_once_with(config["form_id"], last_id=100)
    assert result == ImportResult(people=3, households=0)
    assert import_submission_mock.call_count == 2
    assert import_submission_mock.call_args_list[0].kwargs["submission"] == {"_id": 101, "_uuid": "new-101"}
    assert import_submission_mock.call_args_list[1].kwargs["submission"] == {"_id": 102, "_uuid": "new-102"}

    ona_sync_log["filter"].assert_called_once_with(
        name="ona_9153",
        content_type=ona_sync_log["program_ct"],
        object_id=job.program.id,
    )
    ona_sync_log["update_or_create"].assert_called_once_with(
        name="ona_9153",
        content_type=ona_sync_log["program_ct"],
        object_id=job.program.id,
        defaults={"last_id": "102", "last_update_date": ANY},
    )
    batch.save.assert_called_once_with(update_fields=["status"])


def test_import_data_persists_last_successful_submission_on_error(
    mocker: MockerFixture,
    job,
    config: Config,
    ona_sync_log,
) -> None:
    _mock_atomic(mocker)
    sync_log = mocker.MagicMock()
    sync_log.last_id = "100"
    ona_sync_log["filter"].return_value.first.return_value = sync_log

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    async_job_cls = mocker.patch("country_workspace.contrib.ona.import_processing.AsyncJob")
    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    validation_jobs = mocker.patch("country_workspace.contrib.ona.import_processing.create_validation_jobs")
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = [
        {"_id": 101, "_uuid": "new-101"},
        {"_id": 102, "_uuid": "new-102"},
    ]

    import_submission_mock = mocker.patch("country_workspace.contrib.ona.import_processing.import_submission")
    import_submission_mock.side_effect = [ImportResult(people=1), ValueError("boom")]

    with pytest.raises(ValueError, match="boom"):
        import_data(job)

    ona_sync_log["update_or_create"].assert_called_once_with(
        name="ona_9153",
        content_type=ona_sync_log["program_ct"],
        object_id=job.program.id,
        defaults={"last_id": "101", "last_update_date": ANY},
    )
    async_job_cls.objects.create.assert_not_called()
    postprocessing.assert_not_called()
    validation_jobs.assert_not_called()
    batch_cls.objects.create.return_value.save.assert_not_called()


def test_import_data_reuses_existing_job_batch(
    mocker: MockerFixture,
    job,
    config: Config,
) -> None:
    _mock_atomic(mocker)
    job.batch_id = 777

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch_cls.BatchStatus.LOADING = "LOADING"
    batch_cls.BatchStatus.COMPLETE = "COMPLETE"
    existing_batch = batch_cls.objects.select_for_update.return_value.select_related.return_value.get.return_value
    existing_batch.status = "COMPLETE"

    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = []

    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")

    result = import_data(job)

    assert result == ImportResult(people=0, households=0)
    batch_cls.objects.create.assert_not_called()
    batch_cls.objects.select_for_update.assert_called_once()
    batch_cls.objects.select_for_update.return_value.select_related.assert_called_once_with(
        "program",
        "program__country_office",
    )
    batch_cls.objects.select_for_update.return_value.select_related.return_value.get.assert_called_once_with(pk=777)
    postprocessing.assert_called_once_with(
        existing_batch,
        household_transformer_id=None,
        individual_transformer_id=None,
    )
    job.save.assert_not_called()
    assert existing_batch.save.call_count == 2
    assert existing_batch.status == "COMPLETE"


def test_import_data_passes_transformers_to_postprocessing(mocker: MockerFixture, job, config: Config) -> None:
    _mock_atomic(mocker)
    job.config = {
        **config,
        "household_transformer_id": 10,
        "individual_transformer_id": 20,
    }

    mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = []

    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")

    assert import_data(job) == ImportResult(people=0, households=0)
    postprocessing.assert_called_once()
    assert postprocessing.call_args.kwargs["household_transformer_id"] == 10
    assert postprocessing.call_args.kwargs["individual_transformer_id"] == 20


def test_import_data_creates_validation_jobs_when_enabled(mocker: MockerFixture, job, config: Config) -> None:
    _mock_atomic(mocker)
    job.config = {**config, "validate_after_import": True}

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = []

    mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    validation_queryset = mocker.MagicMock()
    mocker.patch(
        "country_workspace.contrib.ona.import_processing._validation_queryset", return_value=validation_queryset
    )
    create_validation_jobs = mocker.patch("country_workspace.contrib.ona.import_processing.create_validation_jobs")

    import_data(job)

    create_validation_jobs.assert_called_once_with(
        description=f"Validate records for batch {batch.pk}",
        owner=job.owner,
        program=job.program,
        queryset=validation_queryset,
        validation_scope="batch",
    )


def test_import_submission_non_master_detail(mocker: MockerFixture, config: Config) -> None:
    _mock_atomic(mocker)

    batch = mocker.MagicMock()
    create_individual = mocker.patch("country_workspace.contrib.ona.import_processing.create_individual")

    result = import_submission(
        batch=batch,
        submission={
            "_uuid": "uuid-123",
            "name": "Ahmad Ali",
            "age": 35,
        },
        config=config,
    )

    assert result == ImportResult(people=1, households=0)
    create_individual.assert_called_once()

    kwargs = create_individual.call_args.kwargs
    assert kwargs["originating_id"] == "ONA#uuid-123#IND0"
    assert kwargs["row"]["name"] == "Ahmad Ali"
    assert kwargs["row"]["age"] == 35
    assert kwargs["raw_data"] == {
        "_uuid": "uuid-123",
        "name": "Ahmad Ali",
        "age": 35,
    }


def test_import_submission_master_detail(mocker: MockerFixture, config: Config) -> None:
    _mock_atomic(mocker)

    batch = mocker.MagicMock()
    household = mocker.MagicMock()

    create_household = mocker.patch(
        "country_workspace.contrib.ona.import_processing.create_household",
        return_value=household,
    )
    create_individual = mocker.patch("country_workspace.contrib.ona.import_processing.create_individual")

    result = import_submission(
        batch=batch,
        submission={
            "_uuid": "uuid-123",
            "household/name": "Ahmad Household",
            "individuals": [
                {"name": "Ahmad Ali"},
                {"name": "Sara Ahmad"},
            ],
        },
        config={
            **config,
            "master_detail": True,
            "individuals_key": "individuals",
        },
    )

    assert result == ImportResult(people=2, households=1)

    create_household.assert_called_once()
    assert create_household.call_args.kwargs["originating_id"] == "ONA#uuid-123#HH0"
    assert create_household.call_args.kwargs["row"]["household/name"] == "Ahmad Household"
    assert create_household.call_args.kwargs["raw_data"] == {
        "_uuid": "uuid-123",
        "household/name": "Ahmad Household",
    }

    assert create_individual.call_count == 2
    assert create_individual.call_args_list[0].kwargs["raw_data"] == {"name": "Ahmad Ali"}
    assert create_individual.call_args_list[1].kwargs["raw_data"] == {"name": "Sara Ahmad"}
    assert create_individual.call_args_list[0].kwargs["originating_id"] == "ONA#uuid-123#IND0"
    assert create_individual.call_args_list[0].kwargs["household"] is household
    assert create_individual.call_args_list[1].kwargs["originating_id"] == "ONA#uuid-123#IND1"
    assert create_individual.call_args_list[1].kwargs["household"] is household


def test_build_processors_use_ona_preprocessors(mocker: MockerFixture) -> None:
    from country_workspace.contrib.ona import import_processing

    program = mocker.MagicMock()
    processor = mocker.MagicMock()
    build_import_processor = mocker.patch(
        "country_workspace.contrib.ona.import_processing.build_import_processor",
        return_value=processor,
    )

    assert import_processing.build_individual_processor(program, mapping_id=11) is processor
    assert import_processing.build_household_processor(program) is processor

    assert build_import_processor.call_args_list[0].kwargs == {
        "program": program,
        "model": import_processing.Individual,
        "mapping_id": 11,
        "pre_processors": (import_processing.flatten_ona_data, import_processing.filter_ona_sys_fields),
        "post_processors": (),
        "source": import_processing.Batch.BatchSource.ONA,
    }
    assert build_import_processor.call_args_list[1].kwargs == {
        "program": program,
        "model": import_processing.Household,
        "mapping_id": None,
        "pre_processors": (import_processing.flatten_ona_data, import_processing.filter_ona_sys_fields),
        "post_processors": (),
        "source": import_processing.Batch.BatchSource.ONA,
    }


@pytest.mark.parametrize("master_detail", [True, False])
def test_validation_queryset_uses_import_mode(mocker: MockerFixture, config: Config, master_detail: bool) -> None:
    batch = mocker.MagicMock()
    cfg = {**config, "master_detail": master_detail}

    result = _validation_queryset(batch, cfg)

    if master_detail:
        assert result == batch.household_set.filter.return_value.prefetch_related.return_value
        batch.household_set.filter.assert_called_once_with(removed=False)
        batch.household_set.filter.return_value.prefetch_related.assert_called_once_with("members")
    else:
        assert result == batch.individual_set.filter.return_value
        batch.individual_set.filter.assert_called_once_with(household__isnull=True, removed=False)


def test_create_individual_keeps_raw_data_flat(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.pk = 123

    processor = mocker.MagicMock(return_value={"processed": "value"})
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.build_individual_processor",
        return_value=processor,
    )
    individual_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Individual")

    create_individual(
        batch=batch,
        row={"full_name": "Ahmad Ali", "age": 35},
        raw_data={"name": "Ahmad Ali", "age": 35},
        config=config,
        originating_id="ONA#uuid-123#IND0",
    )

    individual_cls.objects.create.assert_called_once()
    created_kwargs = individual_cls.objects.create.call_args.kwargs

    assert created_kwargs["raw_data"] == {
        "name": "Ahmad Ali",
        "age": 35,
    }
    assert "fields" not in created_kwargs["raw_data"]
    assert created_kwargs["flex_fields"] == {"processed": "value"}
    processor.assert_called_once_with({"full_name": "Ahmad Ali", "age": 35})


def test_create_household_keeps_raw_data_flat(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.pk = 123

    processor = mocker.MagicMock(return_value={"processed": "household"})
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.build_household_processor",
        return_value=processor,
    )
    household_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Household")

    create_household(
        batch=batch,
        row={"household_name": "Ahmad Household"},
        raw_data={
            "_uuid": "uuid-123",
            "household/name": "Ahmad Household",
        },
        config={
            **config,
            "household_mapping_id": None,
        },
        originating_id="ONA#uuid-123#HH0",
    )

    household_cls.objects.create.assert_called_once()
    created_kwargs = household_cls.objects.create.call_args.kwargs

    assert created_kwargs["raw_data"] == {
        "_uuid": "uuid-123",
        "household/name": "Ahmad Household",
    }
    assert "fields" not in created_kwargs["raw_data"]
    assert created_kwargs["flex_fields"] == {"processed": "household"}
    processor.assert_called_once_with({"household_name": "Ahmad Household"})


def test_create_individual_uses_external_collector_helper(
    mocker: MockerFixture,
    config: Config,
) -> None:
    batch = mocker.MagicMock()
    batch.program = mocker.MagicMock()

    processor = mocker.MagicMock(
        return_value={
            "full_name": "Collector One",
            "relationship": "NON_BENEFICIARY",
            "role": "PRIMARY",
        }
    )
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.build_individual_processor",
        return_value=processor,
    )

    collector = mocker.MagicMock()
    get_or_create_collector = mocker.patch(
        "country_workspace.contrib.ona.import_processing.get_or_create_collector",
        return_value=(collector, True),
    )
    individual_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Individual")

    result = create_individual(
        batch=batch,
        row={"full_name": "Collector One"},
        raw_data={"name": "Collector One"},
        config=config,
        originating_id="ONA#uuid-123#IND0",
        household=mocker.MagicMock(),
    )

    assert result.individual is collector
    assert result.fields["relationship"] == "NON_BENEFICIARY"

    get_or_create_collector.assert_called_once_with(
        program=batch.program,
        batch=batch,
        individual_fields={
            "full_name": "Collector One",
            "relationship": "NON_BENEFICIARY",
            "role": "PRIMARY",
        },
        raw_data={"name": "Collector One"},
        originating_id="ONA#uuid-123#IND0",
    )
    individual_cls.objects.create.assert_not_called()


def test_set_roles_and_relationships_sets_all_household_refs(
    mocker: MockerFixture,
) -> None:
    from country_workspace.contrib.ona.import_processing import (
        ImportedIndividual,
        set_roles_and_relationships,
    )

    household = mocker.MagicMock()
    household.flex_fields = {}

    primary = mocker.MagicMock()
    primary.id = 101

    alternate = mocker.MagicMock()
    alternate.id = 102

    head = mocker.MagicMock()
    head.id = 103

    set_roles_and_relationships(
        household,
        [
            ImportedIndividual(
                individual=primary,
                fields={"role": "PRIMARY", "relationship": "NON_BENEFICIARY"},
            ),
            ImportedIndividual(
                individual=alternate,
                fields={"role": "ALTERNATE", "relationship": "NON_BENEFICIARY"},
            ),
            ImportedIndividual(
                individual=head,
                fields={"relationship": "HEAD"},
            ),
        ],
    )

    assert household.flex_fields["primary_collector_id"] == 101
    assert household.flex_fields["alternate_collector_id"] == 102
    assert household.flex_fields["head_of_household_id"] == 103
    household.save.assert_called_once_with(update_fields=["flex_fields"])


def test_import_data_emits_data_imported_signal(
    mocker: MockerFixture,
    job,
    config: Config,
    ona_data_imported_signal,
) -> None:
    _mock_atomic(mocker)

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch = batch_cls.objects.create.return_value
    batch.program_id = 123
    batch.id = 456
    batch.household_set.count.return_value = 2
    batch.individual_set.count.return_value = 3

    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = []

    mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")

    result = import_data(job)

    assert result == ImportResult(people=0, households=0)

    ona_data_imported_signal.assert_called_once_with(
        sender=batch_cls,
        program_id=123,
        batch_id=456,
        record_count=5,
        source=batch_cls.BatchSource.ONA,
    )


def test_import_data_timeboxes_and_resumes_same_batch(  # noqa: PLR0915
    mocker: MockerFixture,
    job,
    config: Config,
    ona_constance_config,
    ona_sync_log,
    ona_data_imported_signal,
) -> None:
    _mock_atomic(mocker)
    ona_constance_config.ONA_IMPORT_TIMEBOX_MINUTES = 1
    job.config = {**config, "validate_after_import": True}
    job.program.name = "Test programme"
    clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc), "cursor": None, "people": 0}
    mocker.patch("country_workspace.contrib.ona.import_processing.timezone.now", side_effect=lambda: clock["now"])
    ona_sync_log["filter"].return_value.first.side_effect = lambda: (
        mocker.Mock(last_id=str(clock["cursor"])) if clock["cursor"] is not None else None
    )

    def persist_cursor(**kwargs) -> None:
        clock["cursor"] = int(kwargs["defaults"]["last_id"])

    ona_sync_log["update_or_create"].side_effect = persist_cursor
    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch_cls.BatchStatus.LOADING = "LOADING"
    batch_cls.BatchStatus.COMPLETE = "COMPLETE"
    batch = batch_cls.objects.create.return_value
    batch.id = batch.pk = 777
    batch.status = "LOADING"
    batch.household_set.count.return_value = 0
    batch.individual_set.count.side_effect = lambda: clock["people"]
    batch_cls.objects.select_for_update.return_value.select_related.return_value.get.return_value = batch
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    submissions = [{"_id": value} for value in (1, 2, 3)]
    client_cls.return_value.iter_submissions.side_effect = [submissions, submissions]

    def import_one(**kwargs) -> ImportResult:
        clock["people"] += 1
        clock["now"] += timedelta(seconds=60 if kwargs["submission"]["_id"] == 1 else 1)
        return ImportResult(people=1)

    import_submission_mock = mocker.patch(
        "country_workspace.contrib.ona.import_processing.import_submission", side_effect=import_one
    )
    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    validation_queryset = mocker.Mock()
    mocker.patch(
        "country_workspace.contrib.ona.import_processing._validation_queryset", return_value=validation_queryset
    )
    validation_jobs = mocker.patch("country_workspace.contrib.ona.import_processing.create_validation_jobs")
    async_job_cls = mocker.patch("country_workspace.contrib.ona.import_processing.AsyncJob")
    continuation = async_job_cls.objects.create.return_value

    def queue_after_cursor_saved() -> None:
        assert clock["cursor"] == 1
        assert batch.status == "LOADING"
        assert import_submission_mock.call_count == 1
        postprocessing.assert_not_called()
        validation_jobs.assert_not_called()
        ona_data_imported_signal.assert_not_called()

    continuation.queue.side_effect = queue_after_cursor_saved

    assert import_data(job) == ImportResult(people=1, completed=False)
    batch.save.assert_not_called()
    async_job_cls.objects.create.assert_called_once_with(
        description="ONA / INFORM import: Test programme",
        type=job.type,
        action=job.action,
        file=job.file,
        program=job.program,
        owner=job.owner,
        config=job.config,
        batch=batch,
    )
    continuation.queue.assert_called_once_with()
    continuation.config = job.config
    continuation.batch_id = batch.pk
    continuation.program = job.program
    continuation.owner = job.owner

    assert import_data(continuation) == ImportResult(people=2, completed=True)
    assert clock["cursor"] == 3
    assert clock["people"] == 3
    assert [call.kwargs["submission"]["_id"] for call in import_submission_mock.call_args_list] == [1, 2, 3]
    assert [call.kwargs["last_id"] for call in client_cls.return_value.iter_submissions.call_args_list] == [None, 1]
    batch_cls.objects.create.assert_called_once()
    batch_cls.objects.select_for_update.return_value.select_related.return_value.get.assert_called_once_with(pk=777)
    async_job_cls.objects.create.assert_called_once()
    postprocessing.assert_called_once_with(batch, household_transformer_id=None, individual_transformer_id=None)
    validation_jobs.assert_called_once_with(
        description="Validate records for batch 777",
        owner=job.owner,
        program=job.program,
        queryset=validation_queryset,
        validation_scope="batch",
    )
    assert batch.status == "COMPLETE"
    batch.save.assert_called_once_with(update_fields=["status"])
    ona_data_imported_signal.assert_called_once_with(
        sender=batch_cls,
        program_id=batch.program_id,
        batch_id=777,
        record_count=3,
        source=batch_cls.BatchSource.ONA,
    )


@pytest.mark.parametrize(("minutes", "submissions"), [(0, [{"_id": 1}]), (-1, [{"_id": 1}]), (30, [])])
def test_import_data_completes_disabled_timebox_or_empty_stream(
    mocker: MockerFixture,
    job,
    ona_constance_config,
    minutes: int,
    submissions: list[dict[str, int]],
) -> None:
    _mock_atomic(mocker)
    ona_constance_config.ONA_IMPORT_TIMEBOX_MINUTES = minutes
    clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    mocker.patch("country_workspace.contrib.ona.import_processing.timezone.now", side_effect=lambda: clock["now"])
    mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = submissions

    def import_one(**kwargs) -> ImportResult:
        clock["now"] += timedelta(hours=2)
        return ImportResult(people=1)

    mocker.patch("country_workspace.contrib.ona.import_processing.import_submission", side_effect=import_one)
    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    async_job_cls = mocker.patch("country_workspace.contrib.ona.import_processing.AsyncJob")

    assert import_data(job) == ImportResult(people=len(submissions), completed=True)
    async_job_cls.objects.create.assert_not_called()
    postprocessing.assert_called_once()


def test_import_data_cancellation_preserves_committed_cursor_without_continuation(
    mocker: MockerFixture,
    job,
    ona_sync_log,
    ona_data_imported_signal,
) -> None:
    _mock_atomic(mocker)
    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = [{"_id": 101}, {"_id": 102}]
    import_submission_mock = mocker.patch(
        "country_workspace.contrib.ona.import_processing.import_submission", return_value=ImportResult(people=1)
    )

    def cancel_after_commit(**kwargs) -> None:
        if import_submission_mock.call_count:
            raise GracefulJobCancellationError("cancel requested")

    job.ensure_not_cancelled.side_effect = cancel_after_commit
    async_job_cls = mocker.patch("country_workspace.contrib.ona.import_processing.AsyncJob")
    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    validation_jobs = mocker.patch("country_workspace.contrib.ona.import_processing.create_validation_jobs")

    with pytest.raises(GracefulJobCancellationError, match="cancel requested"):
        import_data(job)

    import_submission_mock.assert_called_once()
    ona_sync_log["update_or_create"].assert_called_once_with(
        name="ona_9153",
        content_type=ona_sync_log["program_ct"],
        object_id=job.program.id,
        defaults={"last_id": "101", "last_update_date": ANY},
    )
    async_job_cls.objects.create.assert_not_called()
    postprocessing.assert_not_called()
    validation_jobs.assert_not_called()
    ona_data_imported_signal.assert_not_called()
    batch_cls.objects.create.return_value.save.assert_not_called()


PHOTO = FlexFileContent(content=b"\xff\xd8\xffphoto", mimetype="image/jpeg", filename="photo.jpg")


def test_import_data_passes_downloaded_attachments_to_import(mocker: MockerFixture, job) -> None:
    _mock_atomic(mocker)
    mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client = client_cls.return_value
    attachment = {"name": "photo.jpg", "mimetype": "image/jpeg", "download_url": "/api/v1/files/1"}
    client.iter_submissions.return_value = [{"_id": 1, "photo": "photo.jpg", "_attachments": [attachment]}]
    client.download.return_value = PHOTO.content
    import_submission_mock = mocker.patch(
        "country_workspace.contrib.ona.import_processing.import_submission", return_value=ImportResult(people=1)
    )

    import_data(job)

    client.download.assert_called_once_with("/api/v1/files/1")
    kwargs = import_submission_mock.call_args.kwargs
    assert kwargs["submission"]["photo"] == pending_marker("photo.jpg")
    assert kwargs["files"] == {"photo.jpg": PHOTO}


@pytest.mark.parametrize(("created", "materialized"), [(True, True), (False, False)])
def test_create_individual_keeps_the_files_of_a_reused_collector(
    mocker: MockerFixture, config: Config, created: bool, materialized: bool
) -> None:
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.build_individual_processor",
        return_value=mocker.MagicMock(return_value={"relationship": "NON_BENEFICIARY"}),
    )
    collector = mocker.MagicMock()
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.get_or_create_collector", return_value=(collector, created)
    )
    materialize = mocker.patch("country_workspace.contrib.ona.import_processing.materialize_pending_files")
    files = {"photo.jpg": PHOTO}

    result = create_individual(
        batch=mocker.MagicMock(), row={}, raw_data={}, config=config, originating_id="ONA#1#IND0", files=files
    )

    assert result.created is created
    assert materialize.called is materialized
    if materialized:
        materialize.assert_called_once_with(collector, files)


def test_create_household_materializes_its_files(mocker: MockerFixture, config: Config) -> None:
    mocker.patch(
        "country_workspace.contrib.ona.import_processing.build_household_processor",
        return_value=mocker.MagicMock(return_value={}),
    )
    household_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Household")
    materialize = mocker.patch("country_workspace.contrib.ona.import_processing.materialize_pending_files")
    files = {"consent.jpg": PHOTO}

    household = create_household(
        batch=mocker.MagicMock(), row={}, raw_data={}, config=config, originating_id="ONA#1#HH0", files=files
    )

    assert household is household_cls.objects.create.return_value
    materialize.assert_called_once_with(household, files)
