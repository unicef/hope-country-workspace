from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.factory import make_client


def test_make_client(mocker: MockerFixture) -> None:
    session_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Session")
    auth_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Auth")
    client_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Client")
    adapter_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.HTTPAdapter")
    api_root_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.APIRoot")

    https_adapter = mocker.MagicMock()
    http_adapter = mocker.MagicMock()
    adapter_cls.side_effect = [https_adapter, http_adapter]

    with override_config(
        DEDUP_API_URL=(url := "https://test.org"),
        DEDUP_API_TOKEN=(token := "token"),
    ):
        with make_client(group_reference_id := "PROGRAM_ID", deduplication_set_id := "SET_ID") as client:
            assert client is client_cls.return_value

    session_cls.assert_called_once_with()
    session = session_cls.return_value.__enter__.return_value

    assert adapter_cls.call_args_list == [
        mocker.call(max_retries=3),
        mocker.call(max_retries=3),
    ]
    assert session.mount.call_args_list == [
        mocker.call("https://", https_adapter),
        mocker.call("http://", http_adapter),
    ]

    assert session.auth is auth_cls.return_value
    auth_cls.assert_called_once_with(token)
    api_root_cls.assert_called_once_with(url)
    client_cls.assert_called_once_with(
        group_reference_id=group_reference_id,
        session=session,
        api_root=api_root_cls.return_value,
        deduplication_set_id=deduplication_set_id,
    )
