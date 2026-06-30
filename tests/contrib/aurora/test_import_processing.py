from typing import Any

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.aurora import import_processing
from country_workspace.contrib.aurora.import_processing import (
    Config,
    ImportResult,
    build_individual_processor,
    create_individual,
    flatten_top2_prefixed,
    import_data,
    import_result,
    prepare_record,
    _validation_queryset,
)
from country_workspace.models.jobs import GracefulJobCancellationError
from tests.contrib.aurora.test_crypto import PRIVATE, _encrypt_fields
from tests.extras.testutils.factories.aurora import RegistrationFactory


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": "Aurora batch",
        "validate_after_import": False,
        "registration_reference_pk": "27",
        "master_detail": False,
    }


@pytest.fixture
def job(mocker: MockerFixture, config: Config):
    job = mocker.MagicMock()
    job.config = config
    job.program.country_office = mocker.MagicMock()
    job.owner = mocker.MagicMock()
    return job


def _mock_sync_log(
    mocker: MockerFixture,
    *,
    last_id: str | None = None,
):
    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_sync_log_name", return_value="sync")
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.ContentType.objects.get_for_model",
        return_value=mocker.MagicMock(),
    )
    sync_log = None
    if last_id is not None:
        sync_log = mocker.MagicMock(last_id=last_id)

    filtered = mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.filter")
    filtered.return_value.first.return_value = sync_log
    return mocker.patch("country_workspace.contrib.aurora.import_processing.SyncLog.objects.update_or_create")


def _mock_atomic(mocker: MockerFixture) -> None:
    atomic = mocker.patch("country_workspace.contrib.aurora.import_processing.transaction.atomic")
    atomic.return_value.__enter__.return_value = None
    atomic.return_value.__exit__.return_value = None


# --- import_data -----------------------------------------------------------------


def test_import_data_requires_registration_reference_pk(job) -> None:
    job.config = {**job.config, "registration_reference_pk": None}

    with pytest.raises(ImportError, match="registration_reference_pk is required"):
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
@pytest.mark.django_db
def test_import_data_calls_client_and_aggregates(
    mocker: MockerFixture,
    job,
    config: Config,
    master_detail: bool,
    imported_results: list[ImportResult],
    expected: ImportResult,
) -> None:
    job.config = {**config, "master_detail": master_detail}
    RegistrationFactory(reference_pk=int(config["registration_reference_pk"]), rsa_private_key=PRIVATE.decode())

    batch_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.AuroraClient")
    client_cls.return_value.get.return_value = [{"pk": "5"}, {"pk": "6"}]

    postprocessing = mocker.patch("country_workspace.contrib.aurora.import_processing.run_batch_postprocessing")
    import_result_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.import_result")
    import_result_mock.side_effect = imported_results

    result = import_data(job)

    assert result == expected
    client_cls.return_value.get.assert_called_once_with(f"registration/{config['registration_reference_pk']}/records/")
    import_result_mock.assert_any_call(batch, {"pk": "5"}, job.config, private_key=PRIVATE.decode())
    import_result_mock.assert_any_call(batch, {"pk": "6"}, job.config, private_key=PRIVATE.decode())
    postprocessing.assert_called_once_with(
        batch,
        household_transformer_id=None,
        individual_transformer_id=None,
    )


@pytest.mark.django_db
def test_import_data_passes_transformers_to_postprocessing(mocker: MockerFixture, job, config: Config) -> None:
    job.config = {
        **config,
        "household_transformer_id": 10,
        "individual_transformer_id": 20,
    }

    batch_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.AuroraClient")
    client_cls.return_value.get.return_value = []

    postprocessing = mocker.patch("country_workspace.contrib.aurora.import_processing.run_batch_postprocessing")

    assert import_data(job) == ImportResult(people=0, households=0)
    postprocessing.assert_called_once_with(
        batch,
        household_transformer_id=10,
        individual_transformer_id=20,
    )


@pytest.mark.django_db
def test_import_data_creates_validation_jobs_when_enabled(mocker: MockerFixture, job, config: Config) -> None:
    job.config = {**config, "validate_after_import": True}

    batch_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.Batch")
    batch = batch_cls.objects.create.return_value

    client_cls = mocker.patch("country_workspace.contrib.aurora.import_processing.AuroraClient")
    client_cls.return_value.get.return_value = []

    mocker.patch("country_workspace.contrib.aurora.import_processing.run_batch_postprocessing")
    validation_queryset = mocker.MagicMock()
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing._validation_queryset", return_value=validation_queryset
    )
    create_validation_jobs = mocker.patch("country_workspace.contrib.aurora.import_processing.create_validation_jobs")

    import_data(job)

    create_validation_jobs.assert_called_once_with(
        description=f"Validate records for batch {batch.pk}",
        owner=job.owner,
        program=job.program,
        queryset=validation_queryset,
    )


@pytest.mark.parametrize(
    "master_detail",
    [
        pytest.param(True, id="master_detail"),
        pytest.param(False, id="people_only"),
    ],
)
def test_validation_queryset_uses_import_mode(mocker: MockerFixture, config: Config, master_detail: bool) -> None:
    batch = mocker.MagicMock()
    config = {**config, "master_detail": master_detail}

    result = _validation_queryset(batch, config)

    if master_detail:
        household_qs = batch.household_set.filter.return_value

        assert result is household_qs.prefetch_related.return_value
        batch.household_set.filter.assert_called_once_with(removed=False)
        household_qs.prefetch_related.assert_called_once_with("members")
        batch.individual_set.filter.assert_not_called()
        return

    assert result is batch.individual_set.filter.return_value
    batch.individual_set.filter.assert_called_once_with(household__isnull=True, removed=False)
    batch.household_set.filter.assert_not_called()


def test_import_data_honors_cancellation_before_start(mocker: MockerFixture, config: Config) -> None:
    job = mocker.MagicMock()
    job.config = config
    job.ensure_not_cancelled.side_effect = GracefulJobCancellationError("cancel requested")

    with pytest.raises(GracefulJobCancellationError):
        import_data(job)


# --- prepare_record --------------------------------------------------------------


def test_prepare_record_passthrough_plaintext_dict() -> None:
    record = {"pk": 1, "fields": {"first_name": "Alice"}}
    assert prepare_record(record, "") == record


def test_prepare_record_raises_when_encrypted_without_key() -> None:
    encrypted = _encrypt_fields({"first_name": "Alice"})
    record = {"pk": 1, "fields": encrypted}

    with pytest.raises(ImportError, match="requires an RSA private key"):
        prepare_record(record, "")


def test_prepare_record_decrypts_encrypted_fields() -> None:
    fields = {"first_name": "Alice", "last_name": "Smith"}
    encrypted = _encrypt_fields(fields)
    record = {"pk": 1, "fields": encrypted}

    prepared = prepare_record(record, PRIVATE.decode())

    assert prepared["fields"] == fields


def test_prepare_record_raises_on_unsupported_fields_type() -> None:
    record = {"pk": 1, "fields": 123}

    with pytest.raises(TypeError, match="unsupported encrypted fields payload type"):
        prepare_record(record, PRIVATE.decode())


def test_prepare_record_raises_when_decryption_fails(mocker: MockerFixture) -> None:
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.decrypt_record_fields",
        side_effect=ValueError("bad data"),
    )
    record = {"pk": 1, "fields": "encrypted-payload"}

    with pytest.raises(ImportError, match="failed to decrypt fields") as exc_info:
        prepare_record(record, PRIVATE.decode())

    assert isinstance(exc_info.value.__cause__, ValueError)


# --- import_result ----------------------------------------------------------------


def test_import_result_skips_when_id_not_greater_than_last(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.program.id = 1

    update_or_create = _mock_sync_log(mocker, last_id="10")
    create_individual_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.create_individual")

    result = import_result(batch, {"pk": "5"}, config)

    assert result == ImportResult(people=0)
    create_individual_mock.assert_not_called()
    update_or_create.assert_not_called()


def test_import_result_success_updates_synclog(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.program.id = 42

    _mock_atomic(mocker)
    update_or_create = _mock_sync_log(mocker)
    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_originating_id", return_value="AUR#7")
    create_individual_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.create_individual")

    result = import_result(batch, {"pk": "7"}, config)

    assert result == ImportResult(people=1)
    create_individual_mock.assert_called_once_with(batch, {"pk": "7"}, config, "AUR#7")
    update_or_create.assert_called_once()


def test_import_result_decrypts_encrypted_fields_before_create(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.program.id = 42

    fields = {"given_name_i_c": "Alice", "family_name_i_c": "Green"}
    encrypted_record = {"pk": "8", "fields": _encrypt_fields(fields)}

    _mock_atomic(mocker)
    _mock_sync_log(mocker)
    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_originating_id", return_value="AUR#8")
    create_individual_mock = mocker.patch("country_workspace.contrib.aurora.import_processing.create_individual")

    import_result(batch, encrypted_record, config, private_key=PRIVATE.decode())

    create_individual_mock.assert_called_once()
    passed_record = create_individual_mock.call_args.args[1]
    assert passed_record["fields"] == fields


def test_import_result_master_detail_creates_households_and_people(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.program.id = 42
    batch.pk = 1

    config = {**config, "master_detail": True}
    result_payload = {
        "pk": "9",
        "fields": {
            "enumerator": "abc",
            "household": [{"hh_field": "hhv"}],
            "individuals": [{"ind_field": "indv"}],
        },
    }

    _mock_atomic(mocker)
    update_or_create = _mock_sync_log(mocker)
    mocker.patch("country_workspace.contrib.aurora.import_processing.get_aurora_originating_id", return_value="AUR#9")
    create_household_and_individuals = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household_and_individuals",
        return_value=(1, 1),
    )

    result = import_result(batch, result_payload, config)

    assert result == ImportResult(people=1, households=1)
    create_household_and_individuals.assert_called_once_with(batch, result_payload, config, "AUR#9")
    update_or_create.assert_called_once()


def test_import_result_wraps_exception(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.program.id = 42

    _mock_atomic(mocker)
    update_or_create = _mock_sync_log(mocker)
    mocker.patch("country_workspace.contrib.aurora.import_processing.create_individual", side_effect=ValueError("boom"))

    with pytest.raises(ImportError) as exc_info:
        import_result(batch, {"pk": "9"}, config)

    message = str(exc_info.value)
    assert "record 9" in message
    assert "Error: boom" in message
    update_or_create.assert_not_called()


def test_import_result_rejects_missing_pk(mocker: MockerFixture, config: Config) -> None:
    batch = mocker.MagicMock()
    batch.program.id = 42

    update_or_create = _mock_sync_log(mocker)

    with pytest.raises(ImportError, match="Missing record pk"):
        import_result(batch, {}, config)

    update_or_create.assert_not_called()


# --- create_household_and_individuals --------------------------------------------


@pytest.mark.parametrize(
    ("fields", "expected_household_fields", "expected_individual_fields"),
    [
        pytest.param(
            {"household": {"hh_field": "hhv"}},
            {"hh_field": "hhv"},
            [],
            id="household_mapping_no_individuals",
        ),
        pytest.param(
            {"household": {"hh_field": "hhv"}, "individuals": {"ind_field": "x"}},
            {"hh_field": "hhv"},
            [{"ind_field": "x"}],
            id="mapping_normalized_to_list",
        ),
        pytest.param(
            {
                "shared": "value",
                "household-info": {"hh_field": "hhv"},
                "individual-details": {"ind_field": "x"},
            },
            {"shared": "value", "hh_field": "hhv"},
            [{"shared": "value", "ind_field": "x"}],
            id="hyphenated_group_keys",
        ),
        pytest.param(
            {"shared_field": "shared_value"},
            {"shared_field": "shared_value"},
            [],
            id="no_groups",
        ),
        pytest.param(
            {"household": None, "individuals": [], "shared_field": "x"},
            {"shared_field": "x"},
            [],
            id="falsy_groups",
        ),
    ],
)
def test_create_household_and_individuals_success_cases(
    mocker: MockerFixture,
    config: Config,
    fields: dict[str, Any],
    expected_household_fields: dict[str, Any],
    expected_individual_fields: list[dict[str, Any]],
) -> None:
    batch = mocker.MagicMock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {"fields": fields}
    household = mocker.MagicMock()

    create_household = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=household,
    )
    create_individual_mock = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_individual",
        return_value=mocker.MagicMock(),
    )

    assert import_processing.create_household_and_individuals(batch, record, config, "AUR#1") == (
        1,
        len(expected_individual_fields),
    )
    create_household.assert_called_once_with(batch, expected_household_fields, config, "AUR#1#HH0")

    if not expected_individual_fields:
        create_individual_mock.assert_not_called()
        return

    assert create_individual_mock.call_args_list == [
        mocker.call(
            batch,
            individual_fields,
            config,
            f"AUR#1#IND{idx}",
            household=household,
        )
        for idx, individual_fields in enumerate(expected_individual_fields)
    ]


def test_create_household_and_individuals_raises_on_individual_error(
    mocker: MockerFixture,
    config: Config,
) -> None:
    batch = mocker.MagicMock()
    batch.pk = 1

    config = {**config, "master_detail": True}
    record = {
        "fields": {
            "household": [{"hh_field": "hhv"}],
            "individuals": [{"ind_field": "x"}],
        }
    }

    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_household",
        return_value=mocker.MagicMock(),
    )
    mocker.patch(
        "country_workspace.contrib.aurora.import_processing.create_individual",
        side_effect=ValueError("boom"),
    )

    with pytest.raises(ImportError, match="Failed to create Aurora individual #0 for record AUR#2") as exc_info:
        import_processing.create_household_and_individuals(batch, record, config, "AUR#2")

    assert isinstance(exc_info.value.__cause__, ValueError)


# --- create_individual / processors ----------------------------------------------


@pytest.mark.parametrize(
    ("record", "has_household", "expected_row", "originating_id"),
    [
        pytest.param({"fields": {"foo": "bar"}}, False, {"foo": "bar"}, "AUR#1", id="fields_envelope"),
        pytest.param({"foo": "bar"}, True, {"foo": "bar"}, "AUR#2", id="extra_household"),
    ],
)
def test_create_individual_creates_record(
    mocker: MockerFixture,
    config: Config,
    record: dict[str, Any],
    has_household: bool,
    expected_row: dict[str, Any],
    originating_id: str,
) -> None:
    batch = mocker.MagicMock()
    batch.pk = 5
    household = mocker.MagicMock() if has_household else None

    processor = mocker.MagicMock(return_value={"x": "y"})
    build_processor = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_individual_processor",
        return_value=processor,
    )
    create_individual_mock = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.Individual.objects.create"
    )

    kwargs = {"household": household} if has_household else {}
    result = create_individual(batch, record, config, originating_id, **kwargs)

    build_processor.assert_called_once_with(batch.program, mapping_id=None)
    processor.assert_called_once_with(expected_row)
    create_individual_mock.assert_called_once_with(
        batch_id=5,
        name="",
        household=household,
        originating_id=originating_id,
        flex_fields={"x": "y"},
        raw_data=record,
    )
    assert result is create_individual_mock.return_value


def test_build_individual_processor_builds_aurora_import_processor(mocker: MockerFixture) -> None:
    program = mocker.MagicMock()
    processor = mocker.MagicMock()
    build_import_processor = mocker.patch(
        "country_workspace.contrib.aurora.import_processing.build_import_processor",
        return_value=processor,
    )

    result = build_individual_processor(program, mapping_id=11)

    assert result is processor
    build_import_processor.assert_called_once_with(
        program=program,
        model=import_processing.Individual,
        mapping_id=11,
        pre_processors=(import_processing.flatten_top2_prefixed,),
        post_processors=(import_processing.make_full_name,),
        source=import_processing.Batch.BatchSource.AURORA,
    )


# --- flatten_top2_prefixed / make_full_name --------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(
            {
                "household-info": [{"admin1_h_c": "FO001"}],
                "intro-and-consent": [{"consent_h_c": True, "enumerator_code": "TestEnum001"}],
                "individual-details": [
                    {
                        "email_i_c": "tester@example.org",
                        "given_name_i_c": "Zara",
                        "family_name_i_c": "Kowalski",
                        "account_details": {"name": "Test Bank", "number": "000123456"},
                    }
                ],
            },
            {
                "admin1_h_c": "FO001",
                "consent_h_c": True,
                "enumerator_code": "TestEnum001",
                "email_i_c": "tester@example.org",
                "given_name_i_c": "Zara",
                "family_name_i_c": "Kowalski",
                "account_details_name": "Test Bank",
                "account_details_number": "000123456",
            },
            id="aurora_like_payload",
        ),
        pytest.param(
            {"a": 1, "b": "x", "c": [1, 2]},
            {"a": 1, "b": "x", "c": [1, 2]},
            id="non_mapping_values",
        ),
    ],
)
def test_flatten_top2_prefixed(data: dict[str, Any], expected: dict[str, Any]) -> None:
    assert flatten_top2_prefixed(data) == expected


@pytest.mark.parametrize(
    ("row", "expected", "same_object"),
    [
        pytest.param(
            {"given_name": "Ada", "middle_name": "", "family_name": "Lovelace"},
            {"given_name": "Ada", "middle_name": "", "family_name": "Lovelace", "full_name": "Ada Lovelace"},
            False,
            id="builds_from_parts",
        ),
        pytest.param(
            {"full_name": "Existing Name", "given_name": "Ada", "family_name": "Lovelace"},
            {"full_name": "Existing Name", "given_name": "Ada", "family_name": "Lovelace"},
            True,
            id="keeps_existing",
        ),
    ],
)
def test_make_full_name(row: dict[str, Any], expected: dict[str, Any], same_object: bool) -> None:
    result = import_processing.make_full_name(row)

    assert result == expected
    if same_object:
        assert result is row
