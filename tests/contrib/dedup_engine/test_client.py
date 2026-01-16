from constance.test.unittest import override_config

from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.client import make_client


def test_make_client(mocker: MockerFixture):
    session_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.Session")
    auth_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.Auth")
    client_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.Client")
    http_adapter_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.HTTPAdapter")
    api_root_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.endpoint.APIRoot")

    with (
        override_config(DEDUP_API_URL=(url := "https://test.org")),
        override_config(DEDUP_API_TOKEN=(token := "token")),
    ):
        client = make_client(program_id := "PROGRAM_ID")

    assert client is client_class_mock.return_value

    session_class_mock.assert_called_once_with()
    session_class_mock.return_value.mount.assert_called_once_with("https://", http_adapter_class_mock.return_value)
    assert session_class_mock.return_value.auth is auth_class_mock.return_value
    http_adapter_class_mock.assert_called_once_with(max_retries=3)
    auth_class_mock.assert_called_once_with(token)
    api_root_class_mock.assert_called_once_with(url)
    client_class_mock.assert_called_once_with(
        program_id, session_class_mock.return_value, api_root_class_mock.return_value
    )
