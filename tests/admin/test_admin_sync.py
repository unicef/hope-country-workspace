from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.contrib import messages
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.sync.context_programs import SyncStep
from country_workspace.models import Office, Program
from country_workspace.admin.base import SyncConfig

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from country_workspace.models import User


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.parametrize(
    ("sync_config", "url_name", "sync_result", "message", "level"),
    [
        (
            SyncConfig(model=Office, step=SyncStep.OFFICES),
            "country_workspace_office_sync",
            {Office._meta.model_name: {"add": 1, "upd": 2}},
            "1 created - 2 updated",
            messages.SUCCESS,
        ),
        (
            SyncConfig(model=Office, step=SyncStep.OFFICES),
            "country_workspace_office_sync",
            {"errors": ["Error 1", "Error 2"], Office._meta.model_name: {"add": 0, "upd": 0}},
            "Error 1; Error 2",
            messages.ERROR,
        ),
        (
            SyncConfig(model=Program, step=SyncStep.PROGRAMS),
            "country_workspace_program_sync",
            {Program._meta.model_name: {"add": 1, "upd": 2}},
            "1 created - 2 updated",
            messages.SUCCESS,
        ),
        (
            SyncConfig(model=Program, step=SyncStep.PROGRAMS),
            "country_workspace_program_sync",
            {"errors": ["Error 3", "Error 4"], Program._meta.model_name: {"add": 0, "upd": 0}},
            "Error 3; Error 4",
            messages.ERROR,
        ),
    ],
    ids=["office_success", "office_errors", "program_success", "program_errors"],
)
@pytest.mark.xdist_group("remote")
def test_admin_sync(app, mocker: MockerFixture, sync_config, url_name, sync_result, message, level):
    mock_sync_context_programs = mocker.patch(
        "country_workspace.admin.base.sync_context_programs",
        return_value=sync_result,
    )
    mock_message_user = mocker.patch("country_workspace.admin.base.BaseModelAdmin.message_user")

    app.get(reverse(f"admin:{url_name}"))

    mock_sync_context_programs.assert_called_once_with(step=sync_config["step"])
    mock_message_user.assert_called_once_with(mocker.ANY, message, level=level)
