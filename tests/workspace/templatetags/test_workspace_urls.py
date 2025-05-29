from unittest.mock import Mock

import pytest
from django.contrib.auth.models import User
from django.db.models import Model
from django.db.models.options import Options
from django.urls import NoReverseMatch
from pytest_mock import MockerFixture

from country_workspace.state import State
from country_workspace.workspaces.templatetags.workspace_urls import ADMIN_CHANGE_VIEW, ADMIN_URL
from src.country_workspace.workspaces.templatetags.workspace_urls import admin_url

TEST_URL = "test_url"


@pytest.fixture
def state(mocker: MockerFixture) -> State:
    return mocker.patch("src.country_workspace.workspaces.templatetags.workspace_urls.state")


@pytest.fixture
def user(state: State) -> User:
    user = Mock(spec=User)
    state.request.user = user
    return user


@pytest.fixture
def options() -> Options:
    options = Mock(spec=Options)
    options.app_label = "test_app"
    options.model_name = "test_model"
    options.proxy_for_model = None
    return options


@pytest.fixture
def model(options: Options) -> Model:
    model = Mock(spec=Model)
    model._meta = options
    return model


@pytest.fixture
def reverse_mock(mocker: MockerFixture) -> Mock:
    reverse = mocker.patch("src.country_workspace.workspaces.templatetags.workspace_urls.reverse")
    reverse.return_value = TEST_URL
    return reverse


def test_admin_url_none_obj(user: User) -> None:
    assert admin_url(None) == ""


def test_admin_url_no_reverse_match(user: User, model: Model, options: Options, reverse_mock: Mock) -> None:
    user.is_staff = True
    reverse_mock.side_effect = NoReverseMatch()
    assert admin_url(model) == ""
    reverse_mock.assert_called_once_with(
        ADMIN_CHANGE_VIEW.format(app=options.app_label, model=options.model_name), args=(model.pk,)
    )


def test_admin_url_user_is_not_staff(user: User, model: Model) -> None:
    user.is_staff = False
    assert admin_url(model) == ""


@pytest.mark.parametrize("has_proxy", [True, False])
def test_admin_url_user_is_staff_model_passed(
    has_proxy: bool, user: User, model: Model, options: Options, reverse_mock: Mock
) -> None:
    user.is_staff = True
    model._meta = options
    options.proxy_for_model = model if has_proxy else None
    assert admin_url(model) == ADMIN_URL.format(url=TEST_URL, query="")
    reverse_mock.assert_called_once_with(
        ADMIN_CHANGE_VIEW.format(app=options.app_label, model=options.model_name), args=(model.pk,)
    )
