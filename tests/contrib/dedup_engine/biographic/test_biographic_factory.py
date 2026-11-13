from uuid import UUID

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.biographic.factory import make_client


@pytest.mark.parametrize(
    "dataset_id", ["5f1d3a0e-8c0b-4f5e-9d7a-2b6c1e4a9f10", UUID("5f1d3a0e-8c0b-4f5e-9d7a-2b6c1e4a9f10")]
)
def test_make_client(mocker: MockerFixture, dataset_id: UUID | str) -> None:
    session_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Session")
    auth_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Auth")
    client_cls = mocker.patch("country_workspace.contrib.dedup_engine.biographic.factory.Client")
    api_root_cls = mocker.patch("country_workspace.contrib.dedup_engine.biographic.factory.APIRoot")
    mocker.patch("country_workspace.contrib.dedup_engine.factory.HTTPAdapter")

    with override_config(DEDUP_API_URL="https://de", DEDUP_API_TOKEN="token"):
        with make_client(business_area_slug="afg", program_code="prog", dataset_id=dataset_id) as client:
            assert client is client_cls.return_value

    session = session_cls.return_value.__enter__.return_value
    assert session.auth is auth_cls.return_value
    auth_cls.assert_called_once_with("token")
    api_root_cls.assert_called_once_with("https://de")
    client_cls.assert_called_once_with(
        business_area_slug="afg",
        program_code="prog",
        session=session,
        api_root=api_root_cls.return_value,
        dataset_id="5f1d3a0e-8c0b-4f5e-9d7a-2b6c1e4a9f10",
    )
