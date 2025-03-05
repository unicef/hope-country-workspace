from typing import cast
from unittest.mock import Mock

import pytest
from constance.test.unittest import override_config
from country_workspace.contrib.kobo.api.data.submission import Submission

from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.sync import (
    make_client,
    extract_household_data,
    prepare_individuals,
    create_household,
    import_data,
)

EMPTY = ""
TOKEN = "token"
MAIN_TOKEN = "main_token"
PROJECT_VIEW_ID = "project-view-id"


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


def test_prepare_individuals(mocker: MockerFixture) -> None:
    individual_class = mocker.patch("country_workspace.contrib.kobo.sync.Individual")
    individual = individual_class.return_value
    batch = Mock()
    data = {
        (individual_records_field := "a"): [
            (
                individual_data := {
                    "full_name": (full_name := "Full Name"),
                }
            )
        ],
    }

    individuals = prepare_individuals(cast(Submission, data), individual_records_field, batch)

    assert individuals == [individual]
    individual_class.assert_called_once_with(batch=batch, name=full_name, flex_fields=individual_data)


def test_create_household(mocker: MockerFixture) -> None:
    batch = Mock()
    households = batch.program.households
    submission = Mock()
    extract_household_data = mocker.patch("country_workspace.contrib.kobo.sync.extract_household_data")
    extract_household_data.return_value.items.return_value = (fields := (("key", "value"),))

    create_household(batch, submission, individual_records_field := "individuals")

    extract_household_data.assert_called_once_with(submission, individual_records_field)
    households.create.assert_called_once_with(batch=batch, flex_fields=dict(fields))


def test_import_data(mocker: MockerFixture) -> None:
    job = Mock()
    job.config = {
        "batch_name": (batch_name := "Batch Name"),
        "individual_records_field": (individual_records_field := "individuals"),
        "country_code": (country_code := "CNT"),
    }
    batch_class = mocker.patch("country_workspace.contrib.kobo.sync.Batch")
    batch = batch_class.objects.create.return_value
    make_client = mocker.patch("country_workspace.contrib.kobo.sync.make_client")
    asset = Mock()
    submission = Mock()
    make_client.return_value.assets = [asset]
    asset.submissions = [submission]
    create_household = mocker.patch("country_workspace.contrib.kobo.sync.create_household")
    household = create_household.return_value
    prepare_individuals = mocker.patch("country_workspace.contrib.kobo.sync.prepare_individuals")
    individual = Mock()
    prepare_individuals.return_value = [individual]

    result = import_data(job)

    assert result == {"households": 1, "individuals": 1}
    batch_class.objects.create.assert_called_once_with(
        name=batch_name,
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=batch_class.BatchSource.KOBO,
    )
    make_client.assert_called_once_with(country_code)
    create_household.assert_called_once_with(batch, submission, individual_records_field)
    prepare_individuals.assert_called_once_with(submission, individual_records_field, batch)
    household.program.individuals.bulk_create.assert_called_once_with([individual])
