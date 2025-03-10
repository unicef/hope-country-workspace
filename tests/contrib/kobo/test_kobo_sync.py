from typing import cast
from unittest.mock import Mock

import pytest
from constance.test.unittest import override_config
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.sync import (
    make_client,
    extract_household_data,
    create_individuals,
    create_household,
    import_data,
    ImportResult,
    import_asset,
    ASSET_CACHE_KEY,
)
from pytest_mock import MockerFixture

EMPTY = ""
TOKEN = "token"
MAIN_TOKEN = "main_token"
PROJECT_VIEW_ID = "project-view-id"
BATCH_NAME = "batch-name"
INDIVIDUAL_RECORDS_FIELD = "individuals"
COUNTRY_CODE = "CNT"


@pytest.mark.parametrize(
    ("master_token", "token", "project_view_id", "expected_token", "expected_project_view_id"),
    [
        (MAIN_TOKEN, EMPTY, PROJECT_VIEW_ID, MAIN_TOKEN, PROJECT_VIEW_ID),
        (MAIN_TOKEN, TOKEN, PROJECT_VIEW_ID, MAIN_TOKEN, PROJECT_VIEW_ID),
        (EMPTY, TOKEN, PROJECT_VIEW_ID, TOKEN, None),
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
    client_class = mocker.patch("country_workspace.contrib.kobo.sync.Client")
    expected_client = client_class.return_value

    with (
        override_config(KOBO_KF_URL=(url := "https://test.org")),
        override_config(KOBO_MASTER_API_TOKEN=master_token),
        override_config(KOBO_API_TOKEN=token),
        override_config(KOBO_PROJECT_VIEW_ID=project_view_id),
    ):
        client = make_client(country_code := "CNT")

    assert client is expected_client
    client_class.assert_called_once_with(
        base_url=url,
        token=expected_token,
        country_code=country_code,
        project_view_id=expected_project_view_id,
    )


def test_extract_household_data() -> None:
    data = {
        (household_field := "a"): 1,
        (individual_records_field := "b"): 2,
    }
    household_data = extract_household_data(cast(Submission, data), individual_records_field)
    assert individual_records_field not in household_data
    assert household_field in household_data
    assert household_data[household_field] == data[household_field]


def test_create_individuals(mocker: MockerFixture) -> None:
    individual_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Individual")
    individual_mock = individual_class_mock.return_value
    batch_mock = Mock()
    household_mock = Mock()
    data = {
        (individual_records_field := "a"): [
            (
                individual_data := {
                    "full_name": (full_name := "Full Name"),
                }
            )
        ],
    }

    individuals = create_individuals(batch_mock, household_mock, cast(Submission, data), individual_records_field)

    assert individuals == len(data[individual_records_field])
    individual_class_mock.assert_called_once_with(batch=batch_mock, name=full_name, flex_fields=individual_data)
    household_mock.program.individuals.bulk_create.assert_called_once_with([individual_mock])


def test_create_household(mocker: MockerFixture) -> None:
    batch_mock = Mock()
    households_mock = batch_mock.program.households
    submission_mock = Mock()
    extract_household_data_mock = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data_mock.return_value.items.return_value = (fields := (("key", "value"),))

    household = create_household(batch_mock, submission_mock, individual_records_field := "individuals")

    assert household == households_mock.create.return_value
    extract_household_data_mock.assert_called_once_with(submission_mock, individual_records_field)
    households_mock.create.assert_called_once_with(batch=batch_mock, flex_fields=dict(fields))


def test_import_asset(mocker: MockerFixture) -> None:
    cache = mocker.patch("country_workspace.contrib.kobo.sync.cache")
    kobo_submission_class = mocker.patch("country_workspace.contrib.kobo.sync.KoboSubmission")
    kobo_submission_class.objects.filter.return_value.values_list.return_value = [(old_submission_id := 42)]
    create_household_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    household_mock = create_household_mock.return_value
    create_individuals_mock = mocker.patch("country_workspace.contrib.kobo.sync.create_individuals")
    create_individuals_mock.return_value = (individuals_counter := 2)
    batch_mock = Mock()
    asset_mock = Mock()
    new_submission_mock = Mock()
    old_submission_mock = Mock()
    old_submission_mock.id = old_submission_id
    asset_mock.submissions = [new_submission_mock, old_submission_mock]

    result = import_asset(batch_mock, asset_mock, (individual_records_field := "individuals"))

    assert result == ImportResult(households=1, individuals=individuals_counter)
    cache.lock.assert_called_once_with(ASSET_CACHE_KEY.format(asset_id=asset_mock.uid))
    kobo_submission_class.objects.filter.assert_called_once_with(asset_uid=asset_mock.uid)
    kobo_submission_class.objects.filter.return_value.values_list.assert_called_once_with("submission_id", flat=True)
    create_household_mock.assert_called_once_with(batch_mock, new_submission_mock, individual_records_field)
    create_individuals_mock.assert_called_once_with(
        batch_mock, household_mock, new_submission_mock, individual_records_field
    )


def test_import_data(mocker: MockerFixture) -> None:
    job_mock = Mock()
    job_mock.config = {
        "batch_name": BATCH_NAME,
        "individual_records_field": INDIVIDUAL_RECORDS_FIELD,
        "country_code": COUNTRY_CODE,
    }
    batch_class_mock = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch_mock = batch_class_mock.objects.create.return_value
    make_client_mock = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    asset_mock = Mock()
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
    make_client_mock.assert_called_once_with(COUNTRY_CODE)
    import_asset_mock.assert_called_once_with(batch_mock, asset_mock, INDIVIDUAL_RECORDS_FIELD)
