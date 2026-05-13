from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.resource import (
    TIMEOUT,
    ActionMixin,
    CreateMixin,
    RetrieveMixin,
    UpdateMixin,
)


def test_create_mixin(mocker: MockerFixture) -> None:
    mixin = CreateMixin()
    mixin.endpoint = endpoint = mocker.Mock()
    mixin.session = session = mocker.Mock()
    body = mocker.Mock()

    assert mixin.create(body) == session.post.return_value.json.return_value

    session.post.assert_called_once_with(str(endpoint), json=body, params=None, timeout=TIMEOUT)
    session.post.return_value.raise_for_status.assert_called_once_with()


def test_create_mixin_with_params(mocker: MockerFixture) -> None:
    mixin = CreateMixin()
    mixin.endpoint = endpoint = mocker.Mock()
    mixin.session = session = mocker.Mock()
    body = mocker.Mock()

    assert mixin.create(body, params={"page": "1"}) == session.post.return_value.json.return_value

    session.post.assert_called_once_with(str(endpoint), json=body, params={"page": "1"}, timeout=TIMEOUT)
    session.post.return_value.raise_for_status.assert_called_once_with()


def test_retrieve_mixin(mocker: MockerFixture) -> None:
    mixin = RetrieveMixin()
    mixin.endpoint = endpoint = mocker.Mock()
    mixin.session = session = mocker.Mock()

    assert mixin.retrieve() == session.get.return_value.json.return_value

    session.get.assert_called_once_with(str(endpoint), timeout=TIMEOUT)
    session.get.return_value.raise_for_status.assert_called_once_with()


def test_update_mixin(mocker: MockerFixture) -> None:
    mixin = UpdateMixin()
    mixin.endpoint = endpoint = mocker.Mock()
    mixin.session = session = mocker.Mock()
    body = mocker.Mock()

    assert mixin.update(body) == session.post.return_value.json.return_value

    session.post.assert_called_once_with(str(endpoint), json=body, timeout=TIMEOUT)
    session.post.return_value.raise_for_status.assert_called_once_with()


def test_action_mixin_without_body(mocker: MockerFixture) -> None:
    mixin = ActionMixin()
    mixin.endpoint = endpoint = mocker.Mock()
    mixin.session = session = mocker.Mock()

    mixin.call()

    session.post.assert_called_once_with(str(endpoint), params=None, timeout=TIMEOUT)
    session.post.return_value.raise_for_status.assert_called_once_with()


def test_action_mixin_with_body_and_params(mocker: MockerFixture) -> None:
    mixin = ActionMixin()
    mixin.endpoint = endpoint = mocker.Mock()
    mixin.session = session = mocker.Mock()
    body = mocker.Mock()

    mixin.call(body, params={"encode_only": "true"})

    session.post.assert_called_once_with(
        str(endpoint),
        params={"encode_only": "true"},
        timeout=TIMEOUT,
        json=body,
    )
    session.post.return_value.raise_for_status.assert_called_once_with()
