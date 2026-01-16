from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.resource import ActionMixin, CreateMixin, RetrieveMixin


def test_create_mixin(mocker: MockerFixture) -> None:
    mixin = CreateMixin()
    mixin.endpoint = (endpoint_mock := mocker.Mock())
    mixin.session = (session_mock := mocker.Mock())
    mixin.create(body_mock := mocker.Mock())

    session_mock.post.assert_called_once_with(str(endpoint_mock), json=body_mock)
    session_mock.post.return_value.raise_for_status.assert_called_once()


def test_retrieve_mixin(mocker: MockerFixture) -> None:
    mixin = RetrieveMixin()
    mixin.endpoint = (endpoint_mock := mocker.Mock())
    mixin.session = (session_mock := mocker.Mock())
    assert mixin.retrieve() == session_mock.get.return_value.json.return_value

    session_mock.get.assert_called_once_with(str(endpoint_mock))
    session_mock.get.return_value.raise_for_status.assert_called_once()


def test_action_mixin(mocker: MockerFixture) -> None:
    mixin = ActionMixin()
    mixin.endpoint = (endpoint_mock := mocker.Mock())
    mixin.session = (session_mock := mocker.Mock())
    mixin.call()

    session_mock.post.assert_called_once_with(str(endpoint_mock))
    session_mock.post.return_value.raise_for_status.assert_called_once()
