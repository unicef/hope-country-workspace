from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.contrib import messages
from pytest_mock import MockerFixture
from django.db.models import Model

from country_workspace.contrib.hope.sync.context_programs import SyncStep as ContextProgramsSyncStep
from country_workspace.contrib.hope.sync.context_geo import SyncStep as ContextGeoSyncStep

from country_workspace.models import Office, Program, Country
from country_workspace.contrib.aurora.models import Registration
from country_workspace.admin.sync import (
    ContextProgramsSyncHandler,
    ContextGeoSyncHandler,
    ContextAuroraSyncHandler,
    ContextAuroraSyncStep,
    SyncConfig,
    SyncHandler,
)


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
    ids=["ctx_program_office", "ctx_program_program", "ctx_geo_country"],
)
def test_admin_sync(
    app: "CWTestApp",
    mocker: MockerFixture,
    model: type[Model],
    step: "ContextProgramsSyncStep | ContextGeoSyncStep",
    sync_handler: SyncHandler[ContextProgramsSyncStep | ContextGeoSyncStep],
    scenario: str,
) -> None:
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


def test_admin_sync_ctx_aurora(app: "CWTestApp", mocker: MockerFixture) -> None:
    mock_message_user = mocker.patch(
        "country_workspace.contrib.aurora.admin.registration.RegistrationAdmin.message_user"
    )
    SyncConfig(model=Registration, step=ContextAuroraSyncStep.REGISTRATIONS, sync_handler=ContextAuroraSyncHandler())
    app.get(reverse("admin:aurora_registration_sync"))
    mock_message_user.assert_called_once_with(mocker.ANY, "Synchronization is scheduled.", level=messages.SUCCESS)


@pytest.mark.parametrize(
    ("handler_class", "sync_func_name", "step_enum"),
    [
        (ContextProgramsSyncHandler, "sync_context_programs", ContextProgramsSyncStep),
        (ContextGeoSyncHandler, "sync_context_geo", ContextGeoSyncStep),
        (ContextAuroraSyncHandler, "sync_context_aurora", ContextAuroraSyncStep),
    ],
    ids=[
        "ContextProgramsSyncHandler",
        "ContextGeoSyncHandler",
        "ContextAuroraSyncHandler",
    ],
)
def test_sync_handlers_forward_to_underlying(
    mocker: MockerFixture,
    handler_class: type[SyncHandler[ContextProgramsSyncStep | ContextGeoSyncStep | ContextAuroraSyncStep]],
    sync_func_name: str,
    step_enum: ContextProgramsSyncStep | ContextGeoSyncStep | ContextAuroraSyncStep,
) -> None:
    fake_return = {"foo": "bar"}
    mock_fn = mocker.patch(f"country_workspace.admin.sync.{sync_func_name}", return_value=fake_return)

    handler = handler_class()
    step = next(iter(step_enum))

    result = handler.sync(step)

    mock_fn.assert_called_once_with(step)
    assert result is fake_return


def test_sync_handler_protocol_default_impl_executes_pass():
    result = SyncHandler.sync(None, step="foo")
    assert result is None
