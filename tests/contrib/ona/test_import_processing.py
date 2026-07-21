from unittest.mock import ANY

import pytest
from pytest_mock import MockerFixture

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
        "individual_field_mapping": {
            "name": "full_name",
            "age": "age",
        },
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
    client_cls.return_value.iter_submissions.assert_called_once_with(config["form_id"])

    import_submission_mock.assert_any_call(batch=batch, submission={"_id": 1, "_uuid": "uuid-1"}, config=job.config)
    import_submission_mock.assert_any_call(batch=batch, submission={"_id": 2, "_uuid": "uuid-2"}, config=job.config)

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

    mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
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


def test_import_data_reuses_existing_job_batch(
    mocker: MockerFixture,
    job,
    config: Config,
) -> None:
    _mock_atomic(mocker)
    job.batch_id = 777

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    existing_batch = batch_cls.objects.select_for_update.return_value.select_related.return_value.get.return_value

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
    existing_batch.save.assert_called_once_with(update_fields=["status"])


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
    mocker.patch("country_workspace.contrib.ona.import_processing._validation_queryset", return_value=validation_queryset)
    create_validation_jobs = mocker.patch("country_workspace.contrib.ona.import_processing.create_validation_jobs")

    import_data(job)

    create_validation_jobs.assert_called_once_with(
        description=f"Validate records for batch {batch.pk}",
        owner=job.owner,
        program=job.program,
        queryset=validation_queryset,
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
    assert kwargs["row"]["full_name"] == "Ahmad Ali"
    assert kwargs["row"]["age"] == 35


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
            "household_field_mapping": {
                "household/name": "household_name",
            },
            "individual_field_mapping": {
                "name": "full_name",
            },
            "individuals_key": "individuals",
        },
    )

    assert result == ImportResult(people=2, households=1)

    create_household.assert_called_once()
    assert create_household.call_args.kwargs["originating_id"] == "ONA#uuid-123#HH0"
    assert create_household.call_args.kwargs["row"]["household_name"] == "Ahmad Household"

    assert create_individual.call_count == 2
    assert create_individual.call_args_list[0].kwargs["originating_id"] == "ONA#uuid-123#IND0"
    assert create_individual.call_args_list[0].kwargs["household"] is household
    assert create_individual.call_args_list[1].kwargs["originating_id"] == "ONA#uuid-123#IND1"
    assert create_individual.call_args_list[1].kwargs["household"] is household


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
        raw_submission={"_uuid": "uuid-123", "name": "Ahmad Ali"},
        config=config,
        originating_id="ONA#uuid-123#IND0",
    )

    individual_cls.objects.create.assert_called_once()
    created_kwargs = individual_cls.objects.create.call_args.kwargs

    assert created_kwargs["raw_data"] == {
        "full_name": "Ahmad Ali",
        "age": 35,
        "_ona_source_submission": {"_uuid": "uuid-123", "name": "Ahmad Ali"},
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
        raw_submission={"_uuid": "uuid-123", "household/name": "Ahmad Household"},
        config={
            **config,
            "household_mapping_id": None,
        },
        originating_id="ONA#uuid-123#HH0",
    )

    household_cls.objects.create.assert_called_once()
    created_kwargs = household_cls.objects.create.call_args.kwargs

    assert created_kwargs["raw_data"] == {
        "household_name": "Ahmad Household",
        "_ona_source_submission": {"_uuid": "uuid-123", "household/name": "Ahmad Household"},
    }
    assert "fields" not in created_kwargs["raw_data"]
    assert created_kwargs["flex_fields"] == {"processed": "household"}
    processor.assert_called_once_with({"household_name": "Ahmad Household"})

