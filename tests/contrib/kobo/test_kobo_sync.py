from typing import cast
from unittest.mock import Mock, call

import pytest
from constance.test.unittest import override_config
from django.contrib.contenttypes.models import ContentType
from pytest_mock import MockerFixture
from typing import TYPE_CHECKING
from country_workspace.contrib.kobo.sync import (
    ACCEPT_JSON_HEADERS,
    AlienFieldsError,
    Config,
    ImportResult,
    create_household,
    create_individuals,
    extract_household_data,
    import_asset,
    import_data,
    is_submission_data_url,
    make_client,
    INDIVIDUAL_FIELDS_TO_UPPERCASE,
    preprocess,
    get_fullname_key,
    HOUSEHOLD_FIELDS_TO_UPPERCASE,
    set_roles_and_relationships,
    get_id_generator,
    get_allowed_fields,
    get_alien_fields,
    check_for_alien_fields,
)
from country_workspace.models import Program
from country_workspace.utils.fields import TO_UPPERCASE_FIELDS
from testutils.factories import (
    BatchFactory,
    DataCheckerFactory,
    FieldsetFactory,
    FlexFieldFactory,
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
    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess")
    partial_mock = mocker.patch("country_workspace.contrib.kobo.sync.partial")
    get_fullname_key_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_fullname_key")
    individual_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Individual")

    mapping_importer_partial = Mock(name="mapping_importer_partial")
    default_fields_partial = Mock(name="default_fields_partial")
    partial_mock.side_effect = [mapping_importer_partial, default_fields_partial]

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

    partial_mock.assert_has_calls(
        [
            call(
                batch_mock.program.apply_mapping_importer,
                individual_class_mock,
                mapping_id=None,
                transformer_id=None,
            ),
            call(batch_mock.program.apply_default_fields, individual_class_mock),
        ]
    )
    assert partial_mock.call_count == 2

    preprocess_mock.assert_called_once_with(
        individual_data,
        INDIVIDUAL_FIELDS_TO_UPPERCASE + TO_UPPERCASE_FIELDS,
        mapping_importer_partial,
        default_fields_partial,
    )

    get_fullname_key_mock.assert_called_once_with(preprocess_mock.return_value)
    individual_class_mock.assert_called_once_with(
        batch=batch_mock,
        raw_data=preprocess_mock.return_value,
        flex_fields=preprocess_mock.return_value,
        originating_id=originating_id,
        household=household_mock,
        name=preprocess_mock.return_value.get.return_value,
    )
    household_mock.program.individuals.bulk_create.assert_called_once_with([individual_class_mock.return_value])


def test_create_household(mocker: MockerFixture, config: Config) -> None:
    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess")
    partial_mock = mocker.patch("country_workspace.contrib.kobo.sync.partial")
    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    household_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Household")
    id_generator_mock = mocker.Mock(name="id_generator")

    mapping_importer_partial = Mock(name="mapping_importer_partial")
    default_fields_partial = Mock(name="default_fields_partial")
    partial_mock.side_effect = [mapping_importer_partial, default_fields_partial]
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

    partial_mock.assert_has_calls(
        [
            call(batch_mock.program.apply_mapping_importer, household_class_mock, mapping_id=None, transformer_id=None),
            call(batch_mock.program.apply_default_fields, household_class_mock),
        ]
    )
    assert partial_mock.call_count == 2

    preprocess_mock.assert_called_once_with(
        extract_household_data_mock.return_value,
        HOUSEHOLD_FIELDS_TO_UPPERCASE,
        mapping_importer_partial,
        default_fields_partial,
    )
    id_generator_mock.assert_called_once()
    preprocess_mock.return_value.__setitem__.assert_called_once_with("household_id", id_generator_mock.return_value)

    batch_mock.program.households.create.assert_called_once_with(
        batch=batch_mock,
        flex_fields=preprocess_mock.return_value,
        raw_data=preprocess_mock.return_value,
        originating_id=originating_id,
    )


def test_create_individuals_passes_transformer_id(mocker: MockerFixture, config: Config) -> None:
    partial_mock = mocker.patch("country_workspace.contrib.kobo.sync.partial")
    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess", return_value={})
    individual_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Individual")

    mapping_partial = Mock(name="mapping_partial")
    default_partial = Mock(name="default_partial")
    partial_mock.side_effect = [mapping_partial, default_partial]

    config_with_transformer = {**config, "individual_transformer_id": 99}
    create_individuals(
        batch_mock := Mock(),
        household_mock := Mock(),  # noqa
        cast("Submission", {INDIVIDUAL_RECORDS_FIELD: [{}]}),
        config_with_transformer,
        originating_id := "orig",  # noqa
    )

    partial_mock.assert_has_calls(
        [
            call(
                batch_mock.program.apply_mapping_importer,
                individual_class_mock,
                mapping_id=None,
                transformer_id=99,
            ),
            call(batch_mock.program.apply_default_fields, individual_class_mock),
        ]
    )
    preprocess_mock.assert_called_once_with(
        {},
        INDIVIDUAL_FIELDS_TO_UPPERCASE + TO_UPPERCASE_FIELDS,
        mapping_partial,
        default_partial,
    )


def test_create_household_passes_transformer_id(mocker: MockerFixture, config: Config) -> None:
    partial_mock = mocker.patch("country_workspace.contrib.kobo.sync.partial")
    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess", return_value={})
    extract_household_data_mock = mocker.patch(
        "country_workspace.contrib.kobo.sync.extract_household_data", return_value={}
    )
    household_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Household")

    mapping_partial = Mock(name="mapping_partial_hh")
    default_partial = Mock(name="default_partial_hh")
    partial_mock.side_effect = [mapping_partial, default_partial]

    config_with_transformer = {**config, "household_transformer_id": 77}
    create_household(
        batch_mock := Mock(),
        submission_mock := Mock(),  # noqa
        config_with_transformer,
        id_generator_mock := Mock(return_value=1),  # noqa
        originating_id := "orig",  # noqa
    )

    partial_mock.assert_has_calls(
        [
            call(
                batch_mock.program.apply_mapping_importer,
                household_class_mock,
                mapping_id=None,
                transformer_id=77,
            ),
            call(batch_mock.program.apply_default_fields, household_class_mock),
        ]
    )
    preprocess_mock.assert_called_once_with(
        extract_household_data_mock.return_value,
        HOUSEHOLD_FIELDS_TO_UPPERCASE,
        mapping_partial,
        default_partial,
    )


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

    assert result == ImportResult(households=2, individuals=len(individual_mocks) * 2)

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

    sync_log.refresh_from_db()
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

    assert result == ImportResult(households=0, individuals=0)

    asset_mock.submissions.assert_called_once_with(min_id=100)

    sync_log.refresh_from_db()
    assert sync_log.last_id == initial_last_id


def test_import_data(mocker: MockerFixture, config: Config) -> None:
    asset_mock = Mock(name="asset")
    asset_mock.uid = config["project_id"]
    job_mock = Mock(name="job")
    job_mock.config = config
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value
    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.get_asset.return_value = asset_mock
    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(
        households=(household_counter := 1), individuals=(individual_counter := 2)
    )
    get_id_generator_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_id_generator")

    create_validation_jobs_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_validation_jobs")

    result = import_data(job_mock)

    assert result == ImportResult(households=household_counter, individuals=individual_counter)
    batch_class_mock.objects.create.assert_called_once_with(
        name=BATCH_NAME,
        program=job_mock.program,
        country_office=job_mock.program.country_office,
        imported_by=job_mock.owner,
        source=batch_class_mock.BatchSource.KOBO,
    )
    make_client_mock.assert_called_once_with(job_mock.program.country_office.kobo_country_code)
    import_asset_mock.assert_called_once_with(batch_mock, asset_mock, config, get_id_generator_mock.return_value)
    get_id_generator_mock.assert_called_once()

    create_validation_jobs_mock.assert_called_once()


def test_get_fullname_key_key_exists() -> None:
    assert get_fullname_key((key := "full_name",)) == key


def test_get_fullname_key_key_does_not_exist() -> None:
    assert get_fullname_key(()) is None


def test_preprocess(mocker: MockerFixture) -> None:
    normalize_json_mock = mocker.patch("country_workspace.contrib.kobo.sync.normalize_json")
    clean_field_names_mock = mocker.patch("country_workspace.contrib.kobo.sync.clean_field_names")
    partial_mock = mocker.patch("country_workspace.contrib.kobo.sync.partial")
    compose_mock = mocker.patch("country_workspace.contrib.kobo.sync.compose")
    mapping_importer = Mock(name="mapping_importer")
    default_fields_applier = Mock(name="default_fields_applier")
    individual = Mock()
    fields_to_uppercase = ("first", "second")

    assert (
        preprocess(individual, fields_to_uppercase, mapping_importer, default_fields_applier)
        == compose_mock.return_value.return_value
    )
    partial_mock.assert_called_once_with(clean_field_names_mock, fields_to_uppercase=fields_to_uppercase)
    compose_mock.assert_called_once_with(
        normalize_json_mock,
        partial_mock.return_value,
        mapping_importer,
        default_fields_applier,
    )
    compose_mock.return_value.assert_called_once_with(individual)


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

    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess")
    preprocess_mock.return_value = {"household_field": "value"}

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"household_field": "value"}

    # Should not raise
    check_for_alien_fields(batch_mock, submission_mock, config, Mock())


def test_check_for_alien_fields_with_household_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = Mock()
    batch_mock.program.household_checker = Mock(spec=DataChecker)
    batch_mock.program.individual_checker = Mock(spec=DataChecker)

    submission_mock = Mock()
    submission_mock.get.return_value = []

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"known_field": "value", "alien_field": "value"}

    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess")
    preprocess_mock.return_value = {"known_field": "value", "alien_field": "value"}

    get_allowed_fields_mock = mocker.patch("country_workspace.contrib.kobo.sync.get_allowed_fields")
    get_allowed_fields_mock.return_value = {"known_field"}

    with pytest.raises(AlienFieldsError) as exc_info:
        check_for_alien_fields(batch_mock, submission_mock, config, Mock())

    assert exc_info.value.household_alien_fields == {"alien_field"}
    assert exc_info.value.individual_alien_fields == set()


def test_check_for_alien_fields_with_individual_aliens(mocker: MockerFixture, config: Config) -> None:
    from hope_flex_fields.models import DataChecker

    batch_mock = Mock()
    batch_mock.program.household_checker = Mock(spec=DataChecker)
    batch_mock.program.individual_checker = Mock(spec=DataChecker)

    submission_mock = Mock()
    submission_mock.get.return_value = [{"known_field": "value", "alien_individual_field": "value"}]

    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value = {"household_field": "value"}

    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess")
    # First call for household, second for individual
    preprocess_mock.side_effect = [
        {"household_field": "value"},
        {"known_field": "value", "alien_individual_field": "value"},
    ]

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
