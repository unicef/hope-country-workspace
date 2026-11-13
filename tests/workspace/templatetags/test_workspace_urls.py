from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.contrib.auth.models import User
from django.db.models import Model
from django.db.models.options import Options
from django.urls import NoReverseMatch, reverse
from pytest_mock import MockerFixture, MockType

from country_workspace.state import State
from country_workspace.workspaces.models import CountryIndividual
from country_workspace.workspaces.templatetags.workspace_urls import (
    ADMIN_CHANGE_VIEW,
    add_preserved_filters,
    admin_href,
    admin_link_html,
    admin_url,
)

TEST_URL = "test_url"


@pytest.fixture
def state(mocker: MockerFixture) -> State:
    return mocker.patch("country_workspace.workspaces.templatetags.workspace_urls.state")


@pytest.fixture
def user(state: State, mocker: MockerFixture) -> User:
    user = mocker.Mock(spec=User)
    state.request.user = user
    return user


@pytest.fixture
def options(mocker: MockerFixture) -> Options:
    options = mocker.Mock(spec=Options)
    options.app_label = "test_app"
    options.model_name = "test_model"
    options.proxy_for_model = None
    return options


@pytest.fixture
def model(options: Options, mocker: MockerFixture) -> Model:
    model = mocker.Mock(spec=Model)
    model._meta = options
    return model


@pytest.fixture
def reverse_mock(mocker: MockerFixture) -> MockType:
    reverse = mocker.patch("country_workspace.workspaces.templatetags.workspace_urls.reverse")
    reverse.return_value = TEST_URL
    return reverse


@pytest.fixture
def preserved_context() -> dict[str, Any]:
    return {
        "opts": CountryIndividual._meta,
        "preserved_filters": urlencode({"_changelist_filters": "household__exact=42&rdp_id=17"}),
    }


def test_admin_url_none_obj(user: User) -> None:
    assert admin_url(None) == ""


def test_admin_url_no_reverse_match(user: User, model: Model, options: Options, reverse_mock: MockType) -> None:
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
    has_proxy: bool, user: User, model: Model, options: Options, reverse_mock: MockType
) -> None:
    user.is_staff = True
    model._meta = options
    options.proxy_for_model = model if has_proxy else None
    assert admin_url(model) == admin_link_html(TEST_URL, "")
    reverse_mock.assert_called_once_with(
        ADMIN_CHANGE_VIEW.format(app=options.app_label, model=options.model_name), args=(model.pk,)
    )


def test_admin_href_is_the_bare_url(user: User, model: Model, reverse_mock: MockType) -> None:
    user.is_staff = True
    assert admin_href(model) == TEST_URL
    assert admin_href(model, household__exact=1) == f"{TEST_URL}?household__exact=1"


def test_admin_href_user_is_not_staff(user: User, model: Model) -> None:
    user.is_staff = False
    assert admin_href(model) == ""


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        ("change", {"_changelist_filters": ["household__exact=42&rdp_id=17"]}),
        ("changelist", {"household__exact": ["42"], "rdp_id": ["17"]}),
    ],
)
def test_add_preserved_filters(preserved_context: dict[str, Any], view: str, expected: dict[str, list[str]]) -> None:
    url = reverse(f"workspace:workspaces_countryindividual_{view}", args=[1] if view == "change" else None)

    result = add_preserved_filters(preserved_context, url)

    assert parse_qs(urlsplit(result).query) == expected


def test_add_preserved_filters_keeps_explicit_query(preserved_context: dict[str, Any]) -> None:
    url = reverse("workspace:workspaces_countryindividual_change", args=[1], query={"_changelist_filters": "rdp_id=23"})

    result = add_preserved_filters(preserved_context, url)

    assert parse_qs(urlsplit(result).query) == {"_changelist_filters": ["rdp_id=23"]}
