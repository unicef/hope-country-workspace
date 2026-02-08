from typing import cast
from unittest.mock import ANY, Mock

import pytest
from constance.test.unittest import override_config
from django.contrib.contenttypes.models import ContentType
from pytest_mock import MockerFixture
from typing import TYPE_CHECKING
from country_workspace.contrib.kobo.sync import (
    ACCEPT_JSON_HEADERS,
    AlienFieldsError,
    build_individual_processor,
    Config,
    ImportResult,
    create_household,
    create_individuals,
    extract_household_data,
    import_asset,
    import_data,
    is_submission_data_url,
    make_client,
    get_fullname_key,
    set_roles_and_relationships,
    get_id_generator,
    get_allowed_fields,
    get_alien_fields,
    check_for_alien_fields,
)
from country_workspace.models import Program, SyncLog
from testutils.factories import (
    BatchFactory,
    DataCheckerFactory,
    FieldsetFactory,
    FlexFieldFactory,
    HouseholdFactory,
    IndividualFactory,
    SyncLogFactory,
)
from testutils.factories.smart_fields import DataCheckerFieldsetFactory

if TYPE_CHECKING:
    from country_workspace.contrib.kobo.api.data.submission import Submission

EMPTY = ""
TOKEN = "token"
MAIN_TOKEN = "main_token"
PROJECT_ID = "project-view-id"
CACHE_TTL = 42
BATCH_NAME = "batch-name"
INDIVIDUAL_RECORDS_FIELD = "individual-records-field"
COUNTRY_CODE = "CNT"


@pytest.fixture
def config() -> Config:
    return {
        "batch_name": BATCH_NAME,
        "project_id": PROJECT_ID,
        "individual_records_field": INDIVIDUAL_RECORDS_FIELD,
        "validate_after_import": True,
        "fail_if_alien": False,
    }


@pytest.mark.parametrize(
    ("master_token", "token", "project_view_id", "expected_token", "expected_project_view_id"),
    [
        (MAIN_TOKEN, EMPTY, PROJECT_ID, MAIN_TOKEN, PROJECT_ID),
        (MAIN_TOKEN, TOKEN, PROJECT_ID, MAIN_TOKEN, PROJECT_ID),
        (EMPTY, TOKEN, PROJECT_ID, TOKEN, None),
    ],
)
def test_make_client(
    mocker: MockerFixture,
    master_token: str,
    token: str,
    project_view_id: str,
    expected_token: str,
    expected_project_view_id: str | None,
) -> None:
    session_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Session")
    auth_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Auth")
    client_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Client")
    data_getter_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.DataGetter")

    with (
        override_config(KOBO_KF_URL=(url := "https://test.org")),
        override_config(KOBO_MASTER_API_TOKEN=master_token),
        override_config(KOBO_API_TOKEN=token),
        override_config(KOBO_CACHE_TTL=CACHE_TTL),
        override_config(KOBO_PROJECT_VIEW_ID=project_view_id),
    ):
        client = make_client(country_code := "CNT")

    assert client is client_class_mock.return_value
    session_class_mock.assert_called_once_with()
    auth_class_mock.assert_called_once_with(expected_token)
    data_getter_class_mock.assert_called_once_with(
        session=session_class_mock.return_value,
        headers=ACCEPT_JSON_HEADERS,
        cache_ttl=CACHE_TTL,
        do_not_use_cache_if=is_submission_data_url,
    )
    client_class_mock.assert_called_once_with(
        data_getter=data_getter_class_mock.return_value,
        base_url=url,
        country_code=country_code,
        project_view_id=expected_project_view_id,
    )


def test_extract_household_data() -> None:
    data = {
        (household_field := "a"): 1,
        (individual_records_field := "b"): 2,
    }
    household_data = extract_household_data(cast("Submission", data), individual_records_field)
    assert individual_records_field not in household_data
    assert household_field in household_data
    assert household_data[household_field] == data[household_field]


def test_create_individuals(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_individual_processor")
    get_fullname_key_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_fullname_key")
    individual_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Individual")
    processor_mock = Mock(return_value={"full_name": "Full Name"})
    build_processor_mock.return_value = processor_mock

    data = {
        INDIVIDUAL_RECORDS_FIELD: [
            (
                individual_data := {
                    "full_name": (_full_name := "Full Name"),
                }
            ),
        ],
    }
    originating_id = "KOB#1#1"
    individuals = create_individuals(
        batch_mock := Mock(name="batch"),
        household_mock := Mock(name="household"),
        cast("Submission", data),
        config,
        originating_id,
    )

    assert individuals == [individual_class_mock.return_value for _ in data[INDIVIDUAL_RECORDS_FIELD]]

    build_processor_mock.assert_called_once_with(batch_mock.program, None, None)
    processor_mock.assert_called_once_with(individual_data)

    get_fullname_key_mock.assert_called_once_with(processor_mock.return_value.keys())
    individual_class_mock.assert_called_once_with(
        batch=batch_mock,
        raw_data=individual_data,
        flex_fields=processor_mock.return_value,
        originating_id=originating_id,
        household=household_mock,
        name=processor_mock.return_value.get.return_value,
    )
    household_mock.program.individuals.bulk_create.assert_called_once_with([individual_class_mock.return_value])


def test_create_household(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_household_processor")
    extract_household_data_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.extract_household_data", return_value={"field": "value"}
    )
    household_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Household")  # noqa
    id_generator_mock = mocker.Mock(name="id_generator")
    processor_mock = Mock(return_value={})
    build_processor_mock.return_value = processor_mock
    originating_id = "KOB#1#1"
    household = create_household(
        batch_mock := Mock(name="batch"),
        submission_mock := Mock(name="submission"),
        config,
        id_generator_mock,
        originating_id,
    )

    assert household == batch_mock.program.households.create.return_value
    extract_household_data_mock.assert_called_once_with(submission_mock, INDIVIDUAL_RECORDS_FIELD)

    build_processor_mock.assert_called_once_with(batch_mock.program, None, None)
    processor_mock.assert_called_once_with(extract_household_data_mock.return_value)
    id_generator_mock.assert_called_once()
    processor_mock.return_value.__setitem__.assert_called_once_with("household_id", id_generator_mock.return_value)

    batch_mock.program.households.create.assert_called_once_with(
        batch=batch_mock,
        flex_fields=processor_mock.return_value,
        raw_data=extract_household_data_mock.return_value,
        originating_id=originating_id,
    )


def test_create_individuals_passes_transformer_id(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_individual_processor")
    individual_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Individual")  # noqa
    build_processor_mock.return_value = Mock(return_value={})

    config_with_transformer = {**config, "individual_transformer_id": 99}
    create_individuals(
        batch_mock := Mock(),
        household_mock := Mock(),  # noqa
        cast("Submission", {INDIVIDUAL_RECORDS_FIELD: [{}]}),
        config_with_transformer,
        originating_id := "orig",  # noqa
    )

    build_processor_mock.assert_called_once_with(batch_mock.program, None, 99)


def test_create_household_passes_transformer_id(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_household_processor")
    extract_household_data_mock = mocker.patch(  # noqa
        "country_workspace.contrib.kobo.sync.extract_household_data", return_value={}
    )
    household_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Household")  # noqa
    build_processor_mock.return_value = Mock(return_value={})

    config_with_transformer = {**config, "household_transformer_id": 77}
    create_household(
        batch_mock := Mock(),
        submission_mock := Mock(),  # noqa
        config_with_transformer,
        id_generator_mock := Mock(return_value=1),  # noqa
        originating_id := "orig",  # noqa
    )

    build_processor_mock.assert_called_once_with(batch_mock.program, None, 77)


@pytest.mark.django_db
def test_import_asset(mocker: MockerFixture, config: Config) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )

    mocker.patch("django.db.transaction.atomic")

    id_generator_mock = mocker.Mock(name="id_generator")
    create_household_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    individual_mocks = [mocker.Mock(), mocker.Mock()]
    create_individuals_mock.return_value = individual_mocks
    set_roles_and_relationships_mock = mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")

    asset_mock = Mock()
    asset_mock.uid = "test_asset_uid"
    submission_1 = Mock(spec=dict)
    submission_1.id = 101
    submission_2 = Mock(spec=dict)
    submission_2.id = 102
    asset_mock.submissions = Mock(return_value=iter([submission_1, submission_2]))

    result = import_asset(
        batch,
        asset_mock,
        config,
        id_generator_mock,
    )

    assert result == ImportResult(households=2, individuals=len(individual_mocks) * 2, completed=True)

    asset_mock.submissions.assert_called_once_with(min_id=100)

    assert create_household_mock.call_count == 2
    assert create_individuals_mock.call_count == 2
    assert set_roles_and_relationships_mock.call_count == 2

    # Verify sync log was updated
    sync_log.refresh_from_db()
    assert sync_log.last_id == "102"


@pytest.mark.django_db
def test_import_asset_with_error(mocker: MockerFixture, config: Config) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )

    mocker.patch("django.db.transaction.atomic")

    id_generator_mock = mocker.Mock(name="id_generator")
    mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    individual_mocks = [mocker.Mock(), mocker.Mock()]
    create_individuals_mock.return_value = individual_mocks

    set_roles_and_relationships_mock = mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")
    set_roles_and_relationships_mock.side_effect = [None, ValueError("Test error")]

    asset_mock = Mock()
    asset_mock.uid = "test_asset_uid"
    submission_1 = Mock(spec=dict)
    submission_1.id = 101
    submission_2 = Mock(spec=dict)
    submission_2.id = 102
    asset_mock.submissions = Mock(return_value=iter([submission_1, submission_2]))
    with pytest.raises(ImportError, match=r"Successfully imported.*at submission 102"):
        import_asset(batch, asset_mock, config, id_generator_mock)

    asset_mock.submissions.assert_called_once_with(min_id=100)
    sync_log.refresh_from_db()
    assert sync_log.last_id == "101"


@pytest.mark.django_db
def test_import_asset_on_error_persists_previous_data(mocker: MockerFixture, config: Config) -> None:
    """
    When import_asset fails on a later submission, earlier data are persisted:
    each submission runs in its own transaction, so a failure rolls back only
    that submission; we assert the first household (and its individuals) remain
    in the DB and the watermark is updated for recovery.
    """
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )

    id_generator_mock = mocker.Mock(name="id_generator")

    def create_household_real(batch, submission, config, id_generator, originating_id):
        return HouseholdFactory(batch=batch, individuals=[])

    def create_individuals_real(batch, household, submission, config, originating_id):
        return [IndividualFactory(batch=batch, household=household)]

    mocker.patch(
        "country_workspace.contrib.kobo.sync.create_household",
        side_effect=create_household_real,
    )
    mocker.patch(
        "country_workspace.contrib.kobo.sync.create_individuals",
        side_effect=create_individuals_real,
    )
    set_roles_and_relationships_mock = mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")
    set_roles_and_relationships_mock.side_effect = [None, ValueError("fail on second")]

    submission_1 = Mock(spec=dict)
    submission_1.id = 101
    submission_2 = Mock(spec=dict)
    submission_2.id = 102
    asset_mock = Mock()
    asset_mock.uid = "test_asset_uid"
    asset_mock.submissions = Mock(return_value=iter([submission_1, submission_2]))

    with pytest.raises(ImportError, match=r"Successfully imported.*at submission 102"):
        import_asset(batch, asset_mock, config, id_generator_mock)

    batch.refresh_from_db()
    assert batch.household_set.count() == 1
    assert batch.household_set.first().members.count() == 1

    sync_log = SyncLog.objects.get(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
    )
    assert sync_log.last_id == "101"


@pytest.mark.django_db
def test_import_asset_no_new_submissions(mocker: MockerFixture, config: Config) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )
    initial_last_id = sync_log.last_id

    id_generator_mock = mocker.Mock(name="id_generator")

    asset_mock = Mock()
    asset_mock.uid = "test_asset_uid"
    asset_mock.submissions = Mock(return_value=iter([]))  # No submissions

    result = import_asset(
        batch,
        asset_mock,
        config,
        id_generator_mock,
    )

    assert result == ImportResult(households=0, individuals=0, completed=True)

    asset_mock.submissions.assert_called_once_with(min_id=100)

    sync_log.refresh_from_db()
    assert sync_log.last_id == initial_last_id


def test_import_data(mocker: MockerFixture, config: Config) -> None:
    asset_mock = Mock(name="asset")
    asset_mock.uid = config["project_id"]
    job_mock = Mock(name="job")
    job_mock.config = config
    job_mock.program = Mock()
    job_mock.program.country_office = Mock()
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.owner = Mock()
    job_mock.batch_id = None
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value
    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.get_asset.return_value = asset_mock
    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(
        households=(household_counter := 1), individuals=(individual_counter := 2), completed=True
    )
    get_id_generator_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")

    create_validation_jobs_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")

    result = import_data(job_mock)

    assert result == ImportResult(households=household_counter, individuals=individual_counter, completed=True)
    batch_class_mock.objects.create.assert_called_once_with(
        name=BATCH_NAME,
        program=job_mock.program,
        country_office=job_mock.program.country_office,
        imported_by=job_mock.owner,
        source=batch_class_mock.BatchSource.KOBO,
        status=batch_class_mock.BatchStatus.LOADING,
    )
    make_client_mock.assert_called_once_with(job_mock.program.country_office.kobo_country_code)
    import_asset_mock.assert_called_once_with(
        batch_mock,
        asset_mock,
        config,
        get_id_generator_mock.return_value,
        timebox_seconds=300,
    )
    get_id_generator_mock.assert_called_once()

    create_validation_jobs_mock.assert_called_once()


@pytest.mark.django_db
def test_import_asset_timeboxed_returns_incomplete_and_keeps_watermark(mocker: MockerFixture, config: Config) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="0",
    )

    submission_1 = Mock(spec=dict)
    submission_1.id = 1
    submission_2 = Mock(spec=dict)
    submission_2.id = 2

    asset_mock = Mock()
    asset_mock.uid = "test_asset_uid"
    asset_mock.submissions = Mock(return_value=iter([submission_1, submission_2]))

    create_household_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    create_individuals_mock.return_value = [Mock()]
    mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")

    res = import_asset(
        batch,
        asset_mock,
        config,
        id_generator_mock := mocker.Mock(name="id_generator"),
        timebox_seconds=0,
    )

    assert res == ImportResult(households=1, individuals=1, completed=False)
    create_household_mock.assert_called_once_with(batch, submission_1, config, id_generator_mock, ANY)
    create_individuals_mock.assert_called_once()
    assert SyncLog.objects.get(name="kobo_test_asset_uid").last_id == "1"


def test_import_data_reschedules_when_incomplete(mocker: MockerFixture, config: Config) -> None:
    asset_mock = Mock(name="asset")
    asset_mock.uid = config["project_id"]
    job_mock = Mock(name="job")
    job_mock.config = config
    job_mock.program = Mock()
    job_mock.program.country_office = Mock()
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.owner = Mock()
    job_mock.batch_id = None
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None

    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value
    batch_mock.BatchStatus.LOADING = "LOADING"

    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.get_asset.return_value = asset_mock

    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(households=0, individuals=0, completed=False)

    get_id_generator_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")
    create_validation_jobs_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")

    new_job_mock = Mock()
    async_create_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.AsyncJob.objects.create", return_value=new_job_mock
    )

    res = import_data(job_mock)

    assert res == ImportResult(households=0, individuals=0, completed=False)
    import_asset_mock.assert_called_once_with(
        batch_mock,
        asset_mock,
        config,
        get_id_generator_mock.return_value,
        timebox_seconds=300,
    )
    create_validation_jobs_mock.assert_not_called()
    async_create_mock.assert_called_once()
    new_job_mock.queue.assert_called_once()
    batch_class_mock.objects.select_for_update.return_value.filter.assert_not_called()


def test_import_data_resumes_existing_batch(mocker: MockerFixture, config: Config) -> None:
    """When job.batch_id is set, import_data uses select_for_update().get() and does not create a new batch."""
    asset_mock = Mock(name="asset")
    asset_mock.uid = config["project_id"]
    job_mock = Mock(name="job")
    job_mock.config = config
    job_mock.program = Mock()
    job_mock.program.country_office = Mock()
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.owner = Mock()
    job_mock.batch_id = 42
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None
    job_mock.save = Mock()

    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    resumed_batch = Mock()
    resumed_batch.pk = 42
    resumed_batch.status = batch_class_mock.BatchStatus.LOADING
    qs = batch_class_mock.objects.select_for_update.return_value
    qs.select_related.return_value.get.return_value = resumed_batch

    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.get_asset.return_value = asset_mock

    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(households=2, individuals=3, completed=True)

    get_id_generator_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")
    create_validation_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")

    result = import_data(job_mock)

    assert result == ImportResult(households=2, individuals=3, completed=True)
    batch_class_mock.objects.create.assert_not_called()
    assert batch_class_mock.objects.select_for_update.call_count >= 1
    qs.select_related.assert_called_once_with("program", "program__country_office")
    qs.select_related.return_value.get.assert_called_once_with(pk=42)
    import_asset_mock.assert_called_once_with(
        resumed_batch,
        asset_mock,
        config,
        get_id_generator_mock.return_value,
        timebox_seconds=300,
    )
    create_validation_mock.assert_called_once()


def test_get_fullname_key_key_exists() -> None:
    assert get_fullname_key((key := "full_name",)) == key


def test_get_fullname_key_key_does_not_exist() -> None:
    assert get_fullname_key(()) is None


def test_build_individual_processor() -> None:
    from country_workspace.models import Individual

    program_mock = Mock()
    program_mock.apply_mapping_importer.side_effect = lambda model, data, mapping_id=None, transformer_id=None: {
        **data,
        "mapped": True,
    }
    program_mock.apply_default_fields.side_effect = lambda model, data: {**data, "defaulted": True}

    processor = build_individual_processor(program_mock, mapping_id=1, transformer_id=2)
    result = processor({"group/Field": "value", "relationship": "head"})

    assert result["field"] == "value"
    assert result["relationship"] == "HEAD"
    assert result["mapped"] is True
    assert result["defaulted"] is True

    args, kwargs = program_mock.apply_mapping_importer.call_args
    assert args[0] is Individual
    assert kwargs["mapping_id"] == 1
    assert kwargs["transformer_id"] == 2
    program_mock.apply_default_fields.assert_called_once()
    default_args, _ = program_mock.apply_default_fields.call_args
    assert default_args[0] is Individual


@pytest.mark.parametrize(
    ("individual_flex_fields", "individual_key"),
    [
        pytest.param({"role": "PRIMARY"}, "primary_collector", id="primary collector"),
        pytest.param({"role": "ALTERNATE"}, "alternate_collector", id="alternate collector"),
        pytest.param({"relationship": "HEAD"}, "head_of_household", id="head of household"),
    ],
)
def test_set_roles_and_relationships(
    mocker: MockerFixture, individual_flex_fields: dict[str, str], individual_key: str
) -> None:
    household_mock = mocker.Mock()
    household_mock.flex_fields = {}
    individual_mock = mocker.Mock()
    individual_mock.flex_fields = individual_flex_fields
    set_roles_and_relationships(household_mock, [individual_mock])
    assert individual_key in household_mock.flex_fields
    assert household_mock.flex_fields[individual_key] == individual_mock.id


def test_get_id_generator() -> None:
    id_generator = get_id_generator()
    assert [id_generator() for _ in range(5)] == [1, 2, 3, 4, 5]


@pytest.mark.django_db
def test_get_allowed_fields() -> None:
    checker = DataCheckerFactory()

    def add_field(prefix: str, field_name: str) -> None:
        fieldset = FieldsetFactory()
        FlexFieldFactory(fieldset=fieldset, name=field_name)
        DataCheckerFieldsetFactory(checker=checker, fieldset=fieldset, prefix=prefix)

    add_field("", "field1")
    add_field("fs1_", "field2")
    add_field("fs2_", "field3")

    allowed = get_allowed_fields(checker)

    assert allowed == {"field1", "fs1_field2", "fs2_field3"}


def test_get_allowed_fields_no_checker() -> None:
    allowed = get_allowed_fields(None)
    assert allowed == set()


def test_get_alien_fields() -> None:
    data = {"field1": "value1", "field2": "value2", "alien1": "value3"}
    allowed = {"field1", "field2", "field3"}

    alien = get_alien_fields(data, allowed)

    assert alien == {"alien1"}


def test_get_alien_fields_respects_constance_ignore() -> None:
    data = {"audit": "value1", "uuid": "value2", "field2": "value3"}
    allowed = set()

    with override_config(KOBO_FIELDS_TO_IGNORE="audit, uuid"):
        alien = get_alien_fields(data, allowed)

    assert alien == {"field2"}


def test_get_alien_fields_none_found() -> None:
    data = {"field1": "value1", "field2": "value2"}
    allowed = {"field1", "field2", "field3"}

    alien = get_alien_fields(data, allowed)

    assert alien == set()


def test_check_for_alien_fields_no_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = Mock()
    batch_mock.program.household_checker = Mock(spec=DataChecker)
    batch_mock.program.individual_checker = Mock(spec=DataChecker)

    submission_mock = Mock()
    submission_mock.get.return_value = [{"individual_field": "value"}]

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.return_value = {"household_field", "individual_field"}

    household_processor = Mock(return_value={"household_field": "value"})
    individual_processor = Mock(return_value={"individual_field": "value"})
    build_household_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_household_processor", return_value=household_processor
    )
    build_individual_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor", return_value=individual_processor
    )

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"household_field": "value"}

    # Should not raise
    mapping_importer = Mock()
    check_for_alien_fields(batch_mock, submission_mock, config, mapping_importer)

    build_household_processor_mock.assert_called_once_with(
        batch_mock.program,
        None,
        None,
        apply_defaults=False,
        apply_mapping=False,
        post_processors=(mapping_importer,),
    )
    build_individual_processor_mock.assert_called_once_with(
        batch_mock.program,
        None,
        None,
        apply_defaults=False,
        apply_mapping=False,
        post_processors=(mapping_importer,),
    )
    household_processor.assert_called_once_with(extract_household_data_mock.return_value)
    individual_processor.assert_called_once_with(submission_mock.get.return_value[0])


def test_check_for_alien_fields_with_household_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = Mock()
    batch_mock.program.household_checker = Mock(spec=DataChecker)
    batch_mock.program.individual_checker = Mock(spec=DataChecker)

    submission_mock = Mock()
    submission_mock.get.return_value = []

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"known_field": "value", "alien_field": "value"}

    household_processor = Mock(return_value={"known_field": "value", "alien_field": "value"})
    build_household_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_household_processor", return_value=household_processor
    )

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.return_value = {"known_field"}

    with pytest.raises(AlienFieldsError) as exc_info:
        check_for_alien_fields(batch_mock, submission_mock, config, Mock())

    assert exc_info.value.household_alien_fields == {"alien_field"}
    assert exc_info.value.individual_alien_fields == set()
    build_household_processor_mock.assert_called_once()
    household_processor.assert_called_once_with(extract_household_data_mock.return_value)


def test_check_for_alien_fields_with_individual_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = Mock()
    batch_mock.program.household_checker = Mock(spec=DataChecker)
    batch_mock.program.individual_checker = Mock(spec=DataChecker)

    submission_mock = Mock()
    submission_mock.get.return_value = [{"known_field": "value", "alien_individual_field": "value"}]

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"household_field": "value"}

    household_processor = Mock(return_value={"household_field": "value"})
    individual_processor = Mock(return_value={"known_field": "value", "alien_individual_field": "value"})
    build_household_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_household_processor", return_value=household_processor
    )
    build_individual_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor", return_value=individual_processor
    )

    def get_allowed_fields_side_effect(checker):
        if checker == batch_mock.program.household_checker:
            return {"household_field"}
        return {"known_field"}

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.side_effect = get_allowed_fields_side_effect

    with pytest.raises(AlienFieldsError) as exc_info:
        check_for_alien_fields(batch_mock, submission_mock, config, Mock())

    assert exc_info.value.household_alien_fields == set()
    assert exc_info.value.individual_alien_fields == {"alien_individual_field"}
    build_household_processor_mock.assert_called_once()
    build_individual_processor_mock.assert_called_once()
    household_processor.assert_called_once_with(extract_household_data_mock.return_value)
    individual_processor.assert_called_once_with(submission_mock.get.return_value[0])
