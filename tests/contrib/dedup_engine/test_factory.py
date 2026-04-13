from constance.test import override_config
from pytest_mock import MockerFixture


def test_make_client(mocker: MockerFixture) -> None:
    session_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Session")
    auth_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Auth")
    client_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.Client")
    adapter_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.HTTPAdapter")
    api_root_cls = mocker.patch("country_workspace.contrib.dedup_engine.factory.APIRoot")

    from country_workspace.contrib.dedup_engine.factory import make_client

    with override_config(
        DEDUP_API_URL=(url := "https://test.org"),
        DEDUP_API_TOKEN=(token := "token"),
    ):
        with make_client(program_id := "PROGRAM_ID", deduplication_set_id := "SET_ID") as client:
            assert client is client_cls.return_value

    session_cls.assert_called_once_with()
    session = session_cls.return_value.__enter__.return_value

    assert adapter_cls.call_args_list == [mocker.call(max_retries=3), mocker.call(max_retries=3)]
    assert session.mount.call_args_list == [
        mocker.call("https://", adapter_cls.return_value),
        mocker.call("http://", adapter_cls.return_value),
    ]

    assert session.auth is auth_cls.return_value
    auth_cls.assert_called_once_with(token)
    api_root_cls.assert_called_once_with(url)
    client_cls.assert_called_once_with(
        program_id=program_id,
        session=session,
        api_root=api_root_cls.return_value,
        deduplication_set_id=deduplication_set_id,
    )
