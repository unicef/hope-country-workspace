from typing import cast

import pytest
from constance.test.unittest import override_config
from country_workspace.contrib.kobo.api.data.submission import Submission

from pytest_mock import MockerFixture

from country_workspace.contrib.kobo.sync import make_client, extract_household_data

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
