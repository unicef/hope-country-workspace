from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import pytest
from constance.test.unittest import override_config
from django.contrib.contenttypes.models import ContentType
from pytest_mock import MockerFixture

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.contrib.kobo.sync import (
    ACCEPT_JSON_HEADERS,
    AlienFieldsError,
    build_individual_processor,
    Config,
    ImportedIndividual,
    ImportResult,
    create_household,
    create_individuals,
    extract_household_data,
    filter_kobo_sys_fields,
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
from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.utils.flex_fields import decode_flex_files_blob, to_public_flex_file_value
from testutils.factories import (
    BatchFactory,
    DataCheckerFactory,
    FieldsetFactory,
    FlexFieldFactory,
    HouseholdFactory,
    IndividualFactory,
    ProgramFactory,
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


@pytest.fixture(autouse=True)
def _mock_bitcaster_dispatch(mocker: MockerFixture):
    return mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")


@pytest.fixture
def submission(mocker: MockerFixture) -> Callable[[int], object]:
    def create(pk: int) -> object:
        obj = mocker.MagicMock()
        obj.id = pk
        return obj

    return create


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
    retry_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Retry")
    http_adapter_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.HTTPAdapter")
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
    retry_class_mock.assert_called_once_with(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(("GET",)),
        respect_retry_after_header=True,
    )
    http_adapter_class_mock.assert_called_once_with(max_retries=retry_class_mock.return_value)
    session_class_mock.return_value.mount.assert_called_once_with("https://", http_adapter_class_mock.return_value)
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

    processor_result = mocker.MagicMock()
    processor_result.get.return_value = "Full Name"
    processor_result.items.return_value = [("full_name", "Full Name"), ("photo", "data:image/png;base64,AAA")]
    processor_mock = mocker.MagicMock(return_value=processor_result)
    build_processor_mock.return_value = processor_mock
    individual_class_mock.return_value.pk = None
    data = {
        INDIVIDUAL_RECORDS_FIELD: [
            (
                individual_data := {
                    "full_name": "Full Name",
                }
            ),
        ],
    }
    asset_uid = "asset-id"
    batch_mock = mocker.MagicMock(name="batch")
    batch_mock.import_date.timestamp.return_value = 1_234_567_890.123
    batch_mock.program.individual_checker.split_data.return_value = {
        "fields": {"full_name": "Full Name"},
        "files": {"photo": "data:image/png;base64,AAA"},
    }
    household_mock = mocker.MagicMock(name="household")
    submission_mock = mocker.MagicMock(id=1)
    submission_mock.get.side_effect = data.get

    individuals = create_individuals(
        batch_mock,
        household_mock,
        cast("Submission", submission_mock),
        config,
        asset_uid,
    )

    assert individuals == [
        ImportedIndividual(individual=individual_class_mock.return_value, fields=processor_mock.return_value)
    ]
    build_processor_mock.assert_called_once_with(batch_mock.program, None)
    batch_mock.program.individual_checker.split_data.assert_called_once_with(
        processor_mock.return_value, file_field_names=None
    )
    processor_mock.assert_called_once_with(individual_data)
    get_fullname_key_mock.assert_called_once_with(processor_mock.return_value.keys())
    individual_class_mock.assert_called_once_with(
        batch=batch_mock,
        raw_data=individual_data,
        flex_fields={"full_name": "Full Name"},
        flex_files=mocker.ANY,
        originating_id="KOB#asset-id#1#0001#1234567890123",
        household=household_mock,
        name=processor_result.get.return_value,
    )
    kwargs = individual_class_mock.call_args.kwargs
    files = decode_flex_files_blob(kwargs["flex_files"])
    assert set(files) == {"photo"}
    assert to_public_flex_file_value(files["photo"]) == "data:image/png;base64,AAA"
    household_mock.program.individuals.bulk_create.assert_called_once_with([individual_class_mock.return_value])


def test_create_individuals_routes_collectors_to_get_or_create(mocker: MockerFixture, config: Config) -> None:
    collector_fields = {"full_name": "John Collector", "relationship": "NON_BENEFICIARY"}
    mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor",
        return_value=mocker.MagicMock(return_value=collector_fields),
    )
    get_or_create_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_or_create_collector")
    collector_mock = mocker.MagicMock(name="collector")
    get_or_create_mock.return_value = (collector_mock, True)
    batch_mock = mocker.MagicMock(name="batch")
    batch_mock.import_date.timestamp.return_value = 1_234_567_890.123
    household_mock = mocker.MagicMock(name="household")
    submission_mock = mocker.MagicMock(id=1)
    submission_mock.get.return_value = [collector_fields]

    individuals = create_individuals(
        batch_mock,
        household_mock,
        cast("Submission", submission_mock),
        config,
        "asset-id",
    )

    assert individuals == [ImportedIndividual(individual=collector_mock, fields=collector_fields)]
    get_or_create_mock.assert_called_once_with(
        program=batch_mock.program,
        batch=batch_mock,
        individual_fields=collector_fields,
        raw_data=collector_fields,
        originating_id="KOB#asset-id#1#0001#1234567890123",
        name="John Collector",
    )
    household_mock.program.individuals.bulk_create.assert_called_once_with([])


@pytest.mark.django_db
def test_create_individuals_deduplicates_collectors_across_households(mocker: MockerFixture, config: Config) -> None:
    mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor",
        return_value=dict,
    )
    batch = BatchFactory()
    household_one = HouseholdFactory(batch=batch, individuals=[])
    household_two = HouseholdFactory(batch=BatchFactory(program=batch.program), individuals=[])
    collector_record = {
        "full_name": "John Collector",
        "given_name": "John",
        "family_name": "Collector",
        "relationship": "NON_BENEFICIARY",
        "role": "PRIMARY",
    }
    data = {INDIVIDUAL_RECORDS_FIELD: [collector_record]}
    submission_one = mocker.MagicMock(id=1)
    submission_one.get.side_effect = data.get
    submission_two = mocker.MagicMock(id=2)
    submission_two.get.side_effect = data.get

    individuals_one = create_individuals(batch, household_one, submission_one, config, "asset-id")
    individuals_two = create_individuals(household_two.batch, household_two, submission_two, config, "asset-id")

    collector = individuals_one[0].individual
    assert individuals_two[0].individual.pk == collector.pk
    assert collector.household is None
    assert collector.identity_hash
    assert batch.program.individuals.count() == 1

    set_roles_and_relationships(household_one, individuals_one)
    set_roles_and_relationships(household_two, individuals_two)
    household_one.refresh_from_db()
    household_two.refresh_from_db()
    assert household_one.flex_fields[HOUSEHOLD_ROLE_REF_FIELDS.primary_collector] == collector.pk
    assert household_two.flex_fields[HOUSEHOLD_ROLE_REF_FIELDS.primary_collector] == collector.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("first_role", "second_role", "first_field", "second_field"),
    [
        pytest.param(
            "PRIMARY",
            "ALTERNATE",
            HOUSEHOLD_ROLE_REF_FIELDS.primary_collector,
            HOUSEHOLD_ROLE_REF_FIELDS.alternate_collector,
            id="primary then alternate",
        ),
        pytest.param(
            "ALTERNATE",
            "PRIMARY",
            HOUSEHOLD_ROLE_REF_FIELDS.alternate_collector,
            HOUSEHOLD_ROLE_REF_FIELDS.primary_collector,
            id="alternate then primary",
        ),
    ],
)
def test_create_individuals_uses_current_submission_role_for_reused_collectors(
    mocker: MockerFixture,
    config: Config,
    first_role: str,
    second_role: str,
    first_field: str,
    second_field: str,
) -> None:
    mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor",
        return_value=dict,
    )
    program = ProgramFactory()
    household_one = HouseholdFactory(batch=BatchFactory(program=program), individuals=[])
    household_two = HouseholdFactory(batch=BatchFactory(program=program), individuals=[])
    base_record = {
        "full_name": "John Collector",
        "given_name": "John",
        "family_name": "Collector",
        "relationship": "NON_BENEFICIARY",
    }

    first_submission = mocker.MagicMock(id=1)
    first_submission.get.return_value = [{**base_record, "role": first_role}]
    second_submission = mocker.MagicMock(id=2)
    second_submission.get.return_value = [{**base_record, "role": second_role}]

    first = create_individuals(household_one.batch, household_one, first_submission, config, "asset-id")
    second = create_individuals(household_two.batch, household_two, second_submission, config, "asset-id")

    collector = first[0].individual
    assert second[0].individual.pk == collector.pk
    assert collector.flex_fields.get("role") == first_role

    set_roles_and_relationships(household_one, first)
    set_roles_and_relationships(household_two, second)
    household_one.refresh_from_db()
    household_two.refresh_from_db()

    assert household_one.flex_fields[first_field] == collector.pk
    assert household_two.flex_fields[second_field] == collector.pk
    assert household_two.flex_fields.get(first_field) != collector.pk


@pytest.mark.django_db
def test_create_individuals_keeps_members_and_deduplicates_collectors(mocker: MockerFixture, config: Config) -> None:
    mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor",
        return_value=dict,
    )
    batch = BatchFactory()
    household = HouseholdFactory(batch=batch, individuals=[])
    data = {
        INDIVIDUAL_RECORDS_FIELD: [
            {"full_name": "Member One", "relationship": "HEAD"},
            {"full_name": "John Collector", "relationship": "NON_BENEFICIARY", "role": "PRIMARY"},
        ]
    }

    submission_mock = mocker.MagicMock(id=1)
    submission_mock.get.side_effect = data.get
    individuals = create_individuals(batch, household, submission_mock, config, "asset-id")

    member, collector = individuals[0].individual, individuals[1].individual
    assert member.household == household
    assert member.identity_hash is None
    assert collector.household is None
    assert batch.program.individuals.count() == 2


def test_create_household(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_household_processor")
    extract_household_data_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.extract_household_data",
        return_value={"field": "value"},
    )
    id_generator_mock = mocker.MagicMock(name="id_generator")
    processor_result = mocker.MagicMock()
    processor_result.items.return_value = [("field", "value")]
    processor_mock = mocker.MagicMock(return_value=processor_result)
    build_processor_mock.return_value = processor_mock
    originating_id = "KOB#1#1"
    batch_mock = mocker.MagicMock(name="batch")
    batch_mock.program.household_checker.split_data.return_value = {"fields": {"field": "value"}, "files": {}}
    submission_mock = mocker.MagicMock(name="submission")

    household = create_household(
        batch_mock,
        submission_mock,
        config,
        id_generator_mock,
        originating_id,
    )

    assert household == batch_mock.program.households.create.return_value
    extract_household_data_mock.assert_called_once_with(submission_mock, INDIVIDUAL_RECORDS_FIELD)
    build_processor_mock.assert_called_once_with(batch_mock.program, None)
    batch_mock.program.household_checker.split_data.assert_called_once_with(
        processor_mock.return_value, file_field_names=None
    )
    processor_mock.assert_called_once_with(extract_household_data_mock.return_value)
    id_generator_mock.assert_called_once()
    processor_result.__setitem__.assert_called_once_with("household_id", id_generator_mock.return_value)
    batch_mock.program.households.create.assert_called_once_with(
        batch=batch_mock,
        flex_fields={"field": "value", "household_id": id_generator_mock.return_value},
        flex_files=None,
        raw_data=extract_household_data_mock.return_value,
        originating_id=originating_id,
    )


def test_create_individuals_passes_mapping_id(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_individual_processor")
    mocker.patch("country_workspace.contrib.kobo.sync.Individual")
    build_processor_mock.return_value = mocker.MagicMock(return_value={})

    config_with_mapping = {**config, "individual_mapping_id": 99}
    batch_mock = mocker.MagicMock()
    submission_mock = mocker.MagicMock(id=1)
    submission_mock.get.return_value = [{}]

    create_individuals(batch_mock, mocker.MagicMock(), submission_mock, config_with_mapping, "asset-id")

    build_processor_mock.assert_called_once_with(batch_mock.program, 99)


def test_create_household_passes_mapping_id(mocker: MockerFixture, config: Config) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_household_processor")
    mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data", return_value={})
    build_processor_mock.return_value = mocker.MagicMock(return_value={})

    config_with_mapping = {**config, "household_mapping_id": 77}
    batch_mock = mocker.MagicMock()

    create_household(
        batch_mock,
        mocker.MagicMock(),
        config_with_mapping,
        mocker.MagicMock(return_value=1),
        "orig",
    )

    build_processor_mock.assert_called_once_with(batch_mock.program, 77)
    batch_mock.program.household_checker.split_data.assert_called_once()
    split_arg = batch_mock.program.household_checker.split_data.call_args.args[0]
    assert split_arg["household_id"] == 1


@pytest.mark.django_db
def test_import_asset(mocker: MockerFixture, config: Config, submission) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )

    mocker.patch("django.db.transaction.atomic")

    id_generator_mock = mocker.MagicMock(name="id_generator")
    create_household_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    individual_mocks = [mocker.MagicMock(), mocker.MagicMock()]
    create_individuals_mock.return_value = individual_mocks
    set_roles_and_relationships_mock = mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")

    asset_mock = mocker.MagicMock()
    asset_mock.uid = "test_asset_uid"
    submission_1 = submission(101)
    submission_2 = submission(102)
    asset_mock.submissions.return_value = iter([submission_1, submission_2])

    result = import_asset(
        batch,
        asset_mock,
        config,
        id_generator_mock,
    )

    assert result == ImportResult(households=2, individuals=len(individual_mocks) * 2, completed=True)
    asset_mock.submissions.assert_called_once_with(min_id=100)
    epoch_ms = int(batch.import_date.timestamp() * 1000)
    assert create_household_mock.call_args_list == [
        mocker.call(batch, submission_1, config, id_generator_mock, f"KOB#test_asset_uid#101#{epoch_ms}"),
        mocker.call(batch, submission_2, config, id_generator_mock, f"KOB#test_asset_uid#102#{epoch_ms}"),
    ]
    assert create_individuals_mock.call_args_list == [
        mocker.call(batch, create_household_mock.return_value, submission_1, config, "test_asset_uid", job=None),
        mocker.call(batch, create_household_mock.return_value, submission_2, config, "test_asset_uid", job=None),
    ]
    assert set_roles_and_relationships_mock.call_count == 2

    sync_log.refresh_from_db()
    assert sync_log.last_id == "102"


@pytest.mark.django_db
def test_import_asset_with_error(mocker: MockerFixture, config: Config, submission) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )

    mocker.patch("django.db.transaction.atomic")

    id_generator_mock = mocker.MagicMock(name="id_generator")
    mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    individual_mocks = [mocker.MagicMock(), mocker.MagicMock()]
    create_individuals_mock.return_value = individual_mocks

    set_roles_and_relationships_mock = mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")
    set_roles_and_relationships_mock.side_effect = [None, ValueError("Test error")]

    asset_mock = mocker.MagicMock()
    asset_mock.uid = "test_asset_uid"
    submission_1 = submission(101)
    submission_2 = submission(102)

    asset_mock.submissions.return_value = iter([submission_1, submission_2])

    with pytest.raises(ImportError, match=r"Successfully imported.*at submission 102"):
        import_asset(batch, asset_mock, config, id_generator_mock)

    asset_mock.submissions.assert_called_once_with(min_id=100)
    sync_log.refresh_from_db()
    assert sync_log.last_id == "101"


@pytest.mark.django_db
def test_import_asset_on_error_persists_previous_data(
    mocker: MockerFixture,
    config: Config,
    submission,
) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )

    id_generator_mock = mocker.MagicMock(name="id_generator")

    def create_household_real(batch, submission, config, id_generator, originating_id):
        return HouseholdFactory(batch=batch, individuals=[])

    def create_individuals_real(batch, household, submission, config, asset_uid, job=None):
        return [ImportedIndividual(individual=IndividualFactory(batch=batch, household=household), fields={})]

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

    submission_1 = submission(101)
    submission_2 = submission(102)

    asset_mock = mocker.MagicMock()
    asset_mock.uid = "test_asset_uid"
    asset_mock.submissions.return_value = iter([submission_1, submission_2])

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

    id_generator_mock = mocker.MagicMock(name="id_generator")
    asset_mock = mocker.MagicMock()
    asset_mock.uid = "test_asset_uid"
    asset_mock.submissions.return_value = iter([])

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
    asset_mock = mocker.MagicMock(name="asset")
    asset_mock.uid = config["project_id"]

    job_mock = mocker.MagicMock(name="job")
    job_mock.config = config
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.batch_id = None
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None

    mocker.patch("country_workspace.contrib.kobo.sync.transaction.atomic")
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value

    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.get_asset.return_value = asset_mock

    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(
        households=(household_counter := 1),
        individuals=(individual_counter := 2),
        completed=True,
    )
    get_id_generator_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")
    create_validation_jobs_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")
    postprocessing_mock = mocker.patch("country_workspace.contrib.kobo.sync.run_batch_postprocessing")

    with override_config(KOBO_IMPORT_TIMEBOX_MINUTES=30):
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
        job=job_mock,
        timebox_seconds=1800,
    )
    get_id_generator_mock.assert_called_once()
    postprocessing_mock.assert_called_once_with(
        batch_mock,
        household_transformer_id=None,
        individual_transformer_id=None,
    )
    create_validation_jobs_mock.assert_called_once()


def test_import_data_passes_transformers_to_postprocessing(mocker: MockerFixture, config: Config) -> None:
    asset_mock = mocker.MagicMock(name="asset")
    asset_mock.uid = config["project_id"]

    job_mock = mocker.MagicMock(name="job")
    job_mock.config = {
        **config,
        "household_transformer_id": 10,
        "individual_transformer_id": 20,
    }
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.batch_id = None
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None

    mocker.patch("country_workspace.contrib.kobo.sync.transaction.atomic")
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value

    mocker.patch("country_workspace.contrib.kobo.sync.make_client").return_value.get_asset.return_value = asset_mock
    mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")
    mocker.patch(
        "country_workspace.contrib.kobo.sync.import_asset",
        return_value=ImportResult(households=0, individuals=0, completed=True),
    )
    mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")
    postprocessing_mock = mocker.patch("country_workspace.contrib.kobo.sync.run_batch_postprocessing")

    import_data(job_mock)

    postprocessing_mock.assert_called_once_with(
        batch_mock,
        household_transformer_id=10,
        individual_transformer_id=20,
    )


@pytest.mark.django_db
def test_import_asset_timeboxed_returns_incomplete_and_keeps_watermark(
    mocker: MockerFixture,
    config: Config,
    submission,
) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    SyncLogFactory(
        name="kobo_test_asset_uid",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="0",
    )

    submission_1 = submission(1)
    submission_2 = submission(2)

    asset_mock = mocker.MagicMock()
    asset_mock.uid = "test_asset_uid"
    asset_mock.submissions.return_value = iter([submission_1, submission_2])

    create_household_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    create_individuals_mock.return_value = [mocker.MagicMock()]
    mocker.patch("country_workspace.contrib.kobo.sync.set_roles_and_relationships")

    id_generator_mock = mocker.MagicMock(name="id_generator")
    result = import_asset(
        batch,
        asset_mock,
        config,
        id_generator_mock,
        timebox_seconds=0,
    )

    assert result == ImportResult(households=1, individuals=1, completed=False)
    create_household_mock.assert_called_once_with(
        batch,
        submission_1,
        config,
        id_generator_mock,
        mocker.ANY,
    )
    create_individuals_mock.assert_called_once_with(
        batch,
        create_household_mock.return_value,
        submission_1,
        config,
        mocker.ANY,
        job=None,
    )
    assert SyncLog.objects.get(name="kobo_test_asset_uid").last_id == "1"


def test_import_data_reschedules_when_incomplete(mocker: MockerFixture, config: Config) -> None:
    asset_mock = mocker.MagicMock(name="asset")
    asset_mock.uid = config["project_id"]

    job_mock = mocker.MagicMock(name="job")
    job_mock.config = config
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.batch_id = None
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None

    mocker.patch("country_workspace.contrib.kobo.sync.transaction.atomic")
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value

    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.get_asset.return_value = asset_mock

    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(households=0, individuals=0, completed=False)

    get_id_generator_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")
    create_validation_jobs_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")

    new_job_mock = mocker.MagicMock()
    async_create_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.AsyncJob.objects.create",
        return_value=new_job_mock,
    )

    with override_config(KOBO_IMPORT_TIMEBOX_MINUTES=30):
        result = import_data(job_mock)

    assert result == ImportResult(households=0, individuals=0, completed=False)
    import_asset_mock.assert_called_once_with(
        batch_mock,
        asset_mock,
        config,
        get_id_generator_mock.return_value,
        job=job_mock,
        timebox_seconds=1800,
    )
    create_validation_jobs_mock.assert_not_called()
    async_create_mock.assert_called_once()
    new_job_mock.queue.assert_called_once()
    batch_class_mock.objects.select_for_update.return_value.filter.assert_not_called()


def test_import_data_resumes_existing_batch(mocker: MockerFixture, config: Config) -> None:
    asset_mock = mocker.MagicMock(name="asset")
    asset_mock.uid = config["project_id"]

    job_mock = mocker.MagicMock(name="job")
    job_mock.config = config
    job_mock.program.country_office.kobo_country_code = "ABC"
    job_mock.batch_id = 42
    job_mock.type = "TASK"
    job_mock.action = "import_action"
    job_mock.description = "desc"
    job_mock.file = None

    mocker.patch("country_workspace.contrib.kobo.sync.transaction.atomic")
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    resumed_batch = mocker.MagicMock()
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
    mocker.patch("country_workspace.contrib.kobo.sync.run_batch_postprocessing")

    with override_config(KOBO_IMPORT_TIMEBOX_MINUTES=30):
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
        job=job_mock,
        timebox_seconds=1800,
    )
    create_validation_mock.assert_called_once()


@pytest.mark.django_db
def test_import_asset_re_raises_graceful_cancellation(mocker: MockerFixture, config: Config) -> None:
    batch = BatchFactory()
    program_ct = ContentType.objects.get_for_model(Program)
    SyncLogFactory(
        name="kobo_asset-id",
        content_type=program_ct,
        object_id=batch.program.id,
        last_id="100",
    )
    asset = mocker.MagicMock()
    asset.uid = "asset-id"
    submission = mocker.MagicMock(spec=dict)
    submission.id = 101
    asset.submissions.return_value = iter([submission])

    job = mocker.MagicMock()
    job.ensure_not_cancelled.side_effect = GracefulJobCancellationError("cancel requested")

    with pytest.raises(GracefulJobCancellationError):
        import_asset(batch, asset, config, id_generator=mocker.MagicMock(), job=job)


@pytest.mark.django_db
def test_create_individuals_checks_cancellation_per_individual(mocker: MockerFixture, config: Config) -> None:
    batch = BatchFactory()
    household = HouseholdFactory(batch=batch, individuals=[])

    job = mocker.MagicMock()
    job.ensure_not_cancelled.side_effect = GracefulJobCancellationError("cancel requested")

    submission = {config["individual_records_field"]: [{"some_field": "value"}]}

    with pytest.raises(GracefulJobCancellationError):
        create_individuals(batch, household, submission, config, "asset-id", job=job)

    job.ensure_not_cancelled.assert_called_once_with(refresh=True)


def test_create_individuals_with_job_checks_cancellation_and_continues(
    mocker: MockerFixture,
    config: Config,
) -> None:
    build_processor_mock = mocker.patch("country_workspace.contrib.kobo.sync.build_individual_processor")
    get_fullname_key_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.get_fullname_key",
        return_value="full_name",
    )
    individual_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Individual")
    individual_class_mock.return_value.pk = None
    build_processor_mock.return_value = mocker.MagicMock(side_effect=[{"full_name": "Name 1"}, {"full_name": "Name 2"}])

    job = mocker.MagicMock()
    submission = mocker.MagicMock(id=1)
    submission.get.return_value = [{"full_name": "Name 1"}, {"full_name": "Name 2"}]
    household_mock = mocker.MagicMock(name="household")

    individuals = create_individuals(
        mocker.MagicMock(name="batch"),
        household_mock,
        submission,
        config,
        "asset-id",
        job=job,
    )

    assert [item.individual for item in individuals] == [
        individual_class_mock.return_value,
        individual_class_mock.return_value,
    ]
    assert job.ensure_not_cancelled.call_count == 2
    build_processor_mock.assert_called_once()
    assert get_fullname_key_mock.call_count == 2
    household_mock.program.individuals.bulk_create.assert_called_once_with(
        [individual_class_mock.return_value, individual_class_mock.return_value]
    )


def test_get_fullname_key_key_exists() -> None:
    assert get_fullname_key((key := "full_name",)) == key


def test_get_fullname_key_key_does_not_exist() -> None:
    assert get_fullname_key(()) is None


def test_filter_kobo_sys_fields() -> None:
    data = {
        "kobo_sys__foo": "ui_value",
        "group/kobo_sys__bar": "nested_ui_value",
        "group/Field": "value",
        "relationship": "head",
    }
    filtered = filter_kobo_sys_fields(data)

    assert filtered == {"group/Field": "value", "relationship": "head"}


def test_build_individual_processor(mocker: MockerFixture) -> None:
    from country_workspace.models import Individual

    program_mock = mocker.MagicMock()
    program_mock.apply_mapping_importer.side_effect = lambda model, data, mapping_id=None: {
        **data,
        "mapped": True,
    }
    program_mock.apply_default_fields.side_effect = lambda model, data: {**data, "defaulted": True}

    processor = build_individual_processor(program_mock, mapping_id=1)
    result = processor(
        {
            "group/Field": "value",
            "relationship": "head",
            "kobo_sys__ui_field": "ignored",
            "group/kobo_sys__nested_ui": "also_ignored",
        }
    )

    assert result["field"] == "value"
    assert result["relationship"] == "HEAD"
    assert "kobo_sys__ui_field" not in result
    assert "nested_ui" not in result
    assert result["mapped"] is True
    assert result["defaulted"] is True

    args, kwargs = program_mock.apply_mapping_importer.call_args
    assert args[0] is Individual
    assert kwargs["mapping_id"] == 1
    assert "transformer_id" not in kwargs

    program_mock.apply_default_fields.assert_called_once()
    default_args, _ = program_mock.apply_default_fields.call_args
    assert default_args[0] is Individual


@pytest.mark.parametrize(
    ("individual_flex_fields", "field_name"),
    [
        pytest.param({"role": "PRIMARY"}, HOUSEHOLD_ROLE_REF_FIELDS.primary_collector, id="primary collector"),
        pytest.param({"role": "ALTERNATE"}, HOUSEHOLD_ROLE_REF_FIELDS.alternate_collector, id="alternate collector"),
        pytest.param({"relationship": "HEAD"}, HOUSEHOLD_ROLE_REF_FIELDS.head_of_household, id="head of household"),
    ],
)
def test_set_roles_and_relationships(
    mocker: MockerFixture,
    individual_flex_fields: dict[str, str],
    field_name: str,
) -> None:
    household_mock = mocker.MagicMock()
    household_mock.flex_fields = {}
    individual_mock = mocker.MagicMock()
    individual_mock.flex_fields = {}

    set_roles_and_relationships(
        household_mock,
        [ImportedIndividual(individual=individual_mock, fields=individual_flex_fields)],
    )

    assert household_mock.flex_fields[field_name] == individual_mock.id
    household_mock.save.assert_called_once_with(update_fields=["flex_fields"])


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

    batch_mock = mocker.MagicMock()
    batch_mock.program.household_checker = mocker.MagicMock(spec=DataChecker)
    batch_mock.program.individual_checker = mocker.MagicMock(spec=DataChecker)

    submission_mock = mocker.MagicMock()
    submission_mock.get.return_value = [{"individual_field": "value"}]

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.return_value = {"household_field", "individual_field"}

    household_processor = mocker.MagicMock(return_value={"household_field": "value"})
    individual_processor = mocker.MagicMock(return_value={"individual_field": "value"})
    build_household_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_household_processor",
        return_value=household_processor,
    )
    build_individual_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor",
        return_value=individual_processor,
    )

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"household_field": "value"}

    mapping_importer = mocker.MagicMock()
    check_for_alien_fields(batch_mock, submission_mock, config, mapping_importer)

    build_household_processor_mock.assert_called_once_with(
        batch_mock.program,
        mapping_id=None,
        apply_defaults=False,
        apply_mapping=False,
        post_processors=(mapping_importer,),
    )
    build_individual_processor_mock.assert_called_once_with(
        batch_mock.program,
        mapping_id=None,
        apply_defaults=False,
        apply_mapping=False,
        post_processors=(mapping_importer,),
    )
    household_processor.assert_called_once_with(extract_household_data_mock.return_value)
    individual_processor.assert_called_once_with(submission_mock.get.return_value[0])


def test_check_for_alien_fields_with_household_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = mocker.MagicMock()
    batch_mock.program.household_checker = mocker.MagicMock(spec=DataChecker)
    batch_mock.program.individual_checker = mocker.MagicMock(spec=DataChecker)

    submission_mock = mocker.MagicMock()
    submission_mock.get.return_value = []

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"known_field": "value", "alien_field": "value"}

    household_processor = mocker.MagicMock(return_value={"known_field": "value", "alien_field": "value"})
    build_household_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_household_processor",
        return_value=household_processor,
    )

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.return_value = {"known_field"}

    with pytest.raises(AlienFieldsError) as exc_info:
        check_for_alien_fields(batch_mock, submission_mock, config, mocker.MagicMock())

    assert exc_info.value.household_alien_fields == {"alien_field"}
    assert exc_info.value.individual_alien_fields == set()
    build_household_processor_mock.assert_called_once()
    household_processor.assert_called_once_with(extract_household_data_mock.return_value)


def test_check_for_alien_fields_with_individual_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = mocker.MagicMock()
    batch_mock.program.household_checker = mocker.MagicMock(spec=DataChecker)
    batch_mock.program.individual_checker = mocker.MagicMock(spec=DataChecker)

    submission_mock = mocker.MagicMock()
    submission_mock.get.return_value = [{"known_field": "value", "alien_individual_field": "value"}]

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"household_field": "value"}

    household_processor = mocker.MagicMock(return_value={"household_field": "value"})
    individual_processor = mocker.MagicMock(return_value={"known_field": "value", "alien_individual_field": "value"})
    build_household_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_household_processor",
        return_value=household_processor,
    )
    build_individual_processor_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.build_individual_processor",
        return_value=individual_processor,
    )

    def get_allowed_fields_side_effect(checker):
        if checker == batch_mock.program.household_checker:
            return {"household_field"}
        return {"known_field"}

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.side_effect = get_allowed_fields_side_effect

    with pytest.raises(AlienFieldsError) as exc_info:
        check_for_alien_fields(batch_mock, submission_mock, config, mocker.MagicMock())

    assert exc_info.value.household_alien_fields == set()
    assert exc_info.value.individual_alien_fields == {"alien_individual_field"}
    build_household_processor_mock.assert_called_once()
    build_individual_processor_mock.assert_called_once()
    household_processor.assert_called_once_with(extract_household_data_mock.return_value)
    individual_processor.assert_called_once_with(submission_mock.get.return_value[0])
