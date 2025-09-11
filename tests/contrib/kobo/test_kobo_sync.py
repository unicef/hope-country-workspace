from typing import cast
from unittest.mock import Mock

import pytest
from constance.test.unittest import override_config
from pytest_mock import MockerFixture
from typing import TYPE_CHECKING
from country_workspace.contrib.kobo.sync import (
    ACCEPT_JSON_HEADERS,
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
)
from country_workspace.utils.fields import TO_UPPERCASE_FIELDS

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
    data = {
        INDIVIDUAL_RECORDS_FIELD: [
            (
                individual_data := {
                    "full_name": (_full_name := "Full Name"),
                }
            ),
        ],
    }

    individuals = create_individuals(
        batch_mock := Mock(name="batch"),
        household_mock := Mock(name="household"),
        cast("Submission", data),
        config,
    )

    assert individuals == len(data[INDIVIDUAL_RECORDS_FIELD])

    partial_mock.assert_called_once_with(batch_mock.program.apply_mapping_importer, individual_class_mock)
    preprocess_mock.assert_called_once_with(
        individual_data,
        INDIVIDUAL_FIELDS_TO_UPPERCASE + TO_UPPERCASE_FIELDS,
        partial_mock.return_value,
    )

    get_fullname_key_mock.assert_called_once_with(preprocess_mock.return_value)
    individual_class_mock.assert_called_once_with(
        batch=batch_mock,
        flex_fields=preprocess_mock.return_value,
        household=household_mock,
        name=preprocess_mock.return_value.get.return_value,
    )
    household_mock.program.individuals.bulk_create.assert_called_once_with([individual_class_mock.return_value])


def test_create_household(mocker: MockerFixture, config: Config) -> None:
    preprocess_mock = mocker.patch("country_workspace.contrib.kobo.sync.preprocess")
    partial_mock = mocker.patch("country_workspace.contrib.kobo.sync.partial")
    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    household_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Household")

    household = create_household(
        batch_mock := Mock(name="batch"),
        submission_mock := Mock(name="submission"),
        config,
    )

    assert household == batch_mock.program.households.create.return_value
    extract_household_data_mock.assert_called_once_with(submission_mock, INDIVIDUAL_RECORDS_FIELD)

    partial_mock.assert_called_once_with(batch_mock.program.apply_mapping_importer, household_class_mock)
    preprocess_mock.assert_called_once_with(
        extract_household_data_mock.return_value,
        HOUSEHOLD_FIELDS_TO_UPPERCASE,
        partial_mock.return_value,
    )

    batch_mock.program.households.create.assert_called_once_with(
        batch=batch_mock, flex_fields=preprocess_mock.return_value
    )


def test_import_asset(mocker: MockerFixture, config: Config) -> None:
    kobo_submission_class = mocker.patch("country_workspace.contrib.kobo.sync.KoboSubmission")
    kobo_submission_class.objects.filter.return_value.values_list.return_value = [(old_submission_id := 42)]
    create_household_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    household_mock = create_household_mock.return_value
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    create_individuals_mock.return_value = (individuals_counter := 2)
    asset_mock = Mock()
    new_submission_mock = Mock()
    old_submission_mock = Mock()
    old_submission_mock.id = old_submission_id
    asset_mock.submissions = [new_submission_mock, old_submission_mock]

    result = import_asset(
        batch_mock := Mock(name="batch"),
        asset_mock,
        config,
    )

    assert result == ImportResult(households=1, individuals=individuals_counter)
    kobo_submission_class.objects.filter.assert_called_once_with(asset_uid=asset_mock.uid)
    kobo_submission_class.objects.filter.return_value.values_list.assert_called_once_with("submission_id", flat=True)
    create_household_mock.assert_called_once_with(batch_mock, new_submission_mock, config)
    create_individuals_mock.assert_called_once_with(batch_mock, household_mock, new_submission_mock, config)


def test_import_data(mocker: MockerFixture, config: Config) -> None:
    asset_mock = Mock(name="asset")
    asset_mock.uid = config["project_id"]
    job_mock = Mock(name="job")
    job_mock.config = config
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value
    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    make_client_mock.return_value.assets = [asset_mock]
    import_asset_mock = mocker.patch("country_workspace.contrib.kobo.sync.import_asset")
    import_asset_mock.return_value = ImportResult(
        households=(household_counter := 1), individuals=(individual_counter := 2)
    )

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
    import_asset_mock.assert_called_once_with(batch_mock, asset_mock, config)


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
    individual = Mock()
    fields_to_uppercase = ("first", "second")

    assert preprocess(individual, fields_to_uppercase, mapping_importer) == compose_mock.return_value.return_value
    partial_mock.assert_called_once_with(clean_field_names_mock, fields_to_uppercase=fields_to_uppercase)
    compose_mock.assert_called_once_with(normalize_json_mock, partial_mock.return_value, mapping_importer)
    compose_mock.return_value.assert_called_once_with(individual)
