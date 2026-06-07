import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.ona.import_processing import (
    Config,
    ImportResult,
    get_ona_originating_id,
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
    job.program.country_office = mocker.MagicMock()
    job.owner = mocker.MagicMock()
    return job


@pytest.fixture(autouse=True)
def ona_constance_config(mocker: MockerFixture):
    constance_config = mocker.patch("country_workspace.contrib.ona.import_processing.constance_config")
    constance_config.ONA_API_URL = "https://api.ona.io"
    constance_config.ONA_API_TOKEN = "dummy-token"
    return constance_config


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
    job.config = {**config, "master_detail": master_detail}

    batch_cls = mocker.patch("country_workspace.contrib.ona.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.ona.import_processing.OnaClient")
    client_cls.return_value.iter_submissions.return_value = [{"_uuid": "1"}, {"_uuid": "2"}]

    postprocessing = mocker.patch("country_workspace.contrib.ona.import_processing.run_batch_postprocessing")
    import_submission_mock = mocker.patch("country_workspace.contrib.ona.import_processing.import_submission")
    import_submission_mock.side_effect = imported_results

    result = import_data(job)

    assert result == expected

    client_cls.assert_called_once_with(
        base_url="https://api.ona.io",
        token="dummy-token",
    )
    client_cls.return_value.iter_submissions.assert_called_once_with(config["form_id"])

    import_submission_mock.assert_any_call(batch=batch, submission={"_uuid": "1"}, config=job.config)
    import_submission_mock.assert_any_call(batch=batch, submission={"_uuid": "2"}, config=job.config)

    postprocessing.assert_called_once_with(
        batch,
        household_transformer_id=None,
        individual_transformer_id=None,
    )

    batch_cls.objects.create.assert_called_once()
    batch.save.assert_called_once_with(update_fields=["status"])


def test_import_data_passes_transformers_to_postprocessing(mocker: MockerFixture, job, config: Config) -> None:
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