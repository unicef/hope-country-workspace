from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.contrib import messages
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.sync.context_programs import SyncStep as ContextProgramsSyncStep
from country_workspace.contrib.hope.sync.context_geo import SyncStep as ContextGeoSyncStep

from country_workspace.models import Office, Program, Country
from country_workspace.admin.sync import SyncConfig, ContextProgramsSyncHandler, ContextGeoSyncHandler

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from country_workspace.models import User


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.mark.parametrize("scenario", ["success", "error"], ids=["success", "error"])
@pytest.mark.parametrize(
    ("model", "step", "sync_handler"),
    [
        (
            Office,
            ContextProgramsSyncStep.OFFICES,
            ContextProgramsSyncHandler(),
        ),
        (
            Program,
            ContextProgramsSyncStep.PROGRAMS,
            ContextProgramsSyncHandler(),
        ),
        (
            Country,
            ContextGeoSyncStep.COUNTRIES,
            ContextGeoSyncHandler(),
        ),
    ],
    ids=["office", "program", "country"],
)
def test_admin_sync(app, mocker: MockerFixture, model, step, sync_handler, scenario):
    if scenario == "success":
        sync_result = {model._meta.model_name: {"add": 1, "upd": 2}}
        expected_message = "1 created - 2 updated"
        expected_level = messages.SUCCESS
    else:
        errors = [f"Error 1 for {model._meta.model_name}", f"Error 2 for {model._meta.model_name}"]
        sync_result = {"errors": errors, model._meta.model_name: {"add": 0, "upd": 0}}
        expected_message = "; ".join(errors)
        expected_level = messages.ERROR

    mock_message_user = mocker.patch("country_workspace.admin.sync.SyncAdminMixin.message_user")
    mock_sync = mocker.patch(
        f"country_workspace.admin.sync.{sync_handler.__class__.__name__}.sync",
        return_value=sync_result,
    )

    SyncConfig(model=model, step=step, sync_handler=sync_handler)
    app.get(reverse(f"admin:country_workspace_{model._meta.model_name}_sync"))

    mock_sync.assert_called_once_with(step=step)
    mock_message_user.assert_called_once_with(mocker.ANY, expected_message, level=expected_level)
