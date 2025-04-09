from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.contrib import messages
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.sync.context_programs import SyncStep
from country_workspace.models import Office, Program

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    admin_user: "User",
) -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.parametrize(
    ("admin_class", "model_name", "step", "url_name", "sync_result", "message", "level"),
    [
        (
            "admin.OfficeAdmin",
            Office._meta.model_name,
            SyncStep.OFFICES,
            "country_workspace_office_sync",
            {Office._meta.model_name: {"add": 1, "upd": 2}},
            "1 created - 2 updated",
            messages.SUCCESS,
        ),
        (
            "admin.OfficeAdmin",
            Office._meta.model_name,
            SyncStep.OFFICES,
            "country_workspace_office_sync",
            {"errors": ["Error 1", "Error 2"], Office._meta.model_name: {"add": 0, "upd": 0}},
            "Error 1; Error 2",
            messages.ERROR,
        ),
        (
            "admin.ProgramAdmin",
            Program._meta.model_name,
            SyncStep.PROGRAMS,
            "country_workspace_program_sync",
            {Program._meta.model_name: {"add": 1, "upd": 2}},
            "1 created - 2 updated",
            messages.SUCCESS,
        ),
        (
            "admin.ProgramAdmin",
            Program._meta.model_name,
            SyncStep.PROGRAMS,
            "country_workspace_program_sync",
            {"errors": ["Error 3", "Error 4"], Program._meta.model_name: {"add": 0, "upd": 0}},
            "Error 3; Error 4",
            messages.ERROR,
        ),
    ],
    ids=["office_success", "office_errors", "program_success", "program_errors"],
)
@pytest.mark.xdist_group("remote")
def test_admin_sync(app, mocker: MockerFixture, admin_class, model_name, step, url_name, sync_result, message, level):
    mocker.patch(
        "country_workspace.contrib.hope.sync.context_programs.sync_context_programs",
        return_value=sync_result,
    )
    mock_message_user = mocker.patch(f"country_workspace.{admin_class}.message_user")
    app.get(reverse(f"admin:{url_name}"))
    mock_message_user.assert_called_once_with(mocker.ANY, message, level=level)
