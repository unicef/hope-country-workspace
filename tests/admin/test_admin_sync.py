from typing import TYPE_CHECKING
import pytest
from django.urls import reverse
from django.contrib import messages
from pytest_mock import MockerFixture
from django.db.models import Model
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from country_workspace.models import User

from country_workspace.contrib.hope.sync.context_programs import SyncStep as ContextProgramsSyncStep
from country_workspace.contrib.hope.sync.context_geo import SyncStep as ContextGeoSyncStep
from country_workspace.contrib.aurora.context_aurora import SyncStep as ContextAuroraSyncStep
from country_workspace.models import Office, Program, Country, AreaType, Area
from country_workspace.contrib.aurora.models import Registration
from country_workspace.admin.sync import SyncAdminMixin, run_sync

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
    ("model", "admin_app"),
    [
        (Office, "country_workspace"),
        (Program, "country_workspace"),
        (Country, "country_workspace"),
        (AreaType, "country_workspace"),
        (Area, "country_workspace"),
        (Registration, "aurora"),
    ],
    ids=["Office", "Program", "Country", "AreaType", "Area", "Registration"],
)
@pytest.mark.parametrize("delta_sync", [False, True], ids=["full", "delta"])
@pytest.mark.parametrize("scenario", ["success", "error"], ids=["success", "error"])
def test_admin_sync(
    app: "CWTestApp",
    mocker: MockerFixture,
    model: type[Model],
    admin_app: str,
    delta_sync: bool,
    scenario: str,
) -> None:
    result = (
        {model._meta.model_name: {"add": 1, "upd": 2}}
        if scenario == "success"
        else {"errors": [f"Error 1 for {model._meta.model_name}", f"Error 2 for {model._meta.model_name}"]}
    )
    mock_run = mocker.patch("country_workspace.admin.sync.run_sync", return_value=result)
    mock_msg = mocker.patch.object(SyncAdminMixin, "message_user")

    url_name = (
        f"admin:{admin_app}_{model._meta.model_name}_sync"
        if not delta_sync
        else f"admin:{admin_app}_{model._meta.model_name}_sync_delta"
    )
    expected_text = (
        "Synchronization is scheduled."
        if not delta_sync
        else (
            f"{model._meta.model_name.upper()}: 1 created - 2 updated"
            if scenario == "success"
            else f"Error 1 for {model._meta.model_name} | Error 2 for {model._meta.model_name}"
        )
    )
    expected_level = messages.SUCCESS if not delta_sync or scenario == "success" else messages.ERROR

    response = app.get(reverse(url_name))

    assert response.status_code == 302
    mock_run.assert_called_once()
    cfg = mock_run.call_args.kwargs["config"]
    assert cfg["delta_sync"] is delta_sync
    mock_msg.assert_called_once_with(mocker.ANY, expected_text, level=expected_level)


@pytest.mark.parametrize(
    ("step_member", "handler_path"),
    [
        (
            ContextProgramsSyncStep.OFFICES,
            "hope.sync.context_programs.sync_context_programs",
        ),
        (
            ContextProgramsSyncStep.PROGRAMS,
            "hope.sync.context_programs.sync_context_programs",
        ),
        (
            ContextGeoSyncStep.COUNTRIES,
            "hope.sync.context_geo.sync_context_geo",
        ),
        (
            ContextGeoSyncStep.AREATYPES,
            "hope.sync.context_geo.sync_context_geo",
        ),
        (
            ContextGeoSyncStep.AREAS,
            "hope.sync.context_geo.sync_context_geo",
        ),
        (
            ContextAuroraSyncStep.REGISTRATIONS,
            "aurora.context_aurora.sync_context_aurora",
        ),
    ],
    ids=["Program_OFFICES", "Program_PROGRAMS", "Geo_COUNTRIES", "Geo_AREATYPES", "Geo_AREAS", "Aurora_REGISTRATIONS"],
)
@pytest.mark.parametrize("delta_sync", [False, True], ids=["full", "delta"])
def test_run_sync_invokes_correct_handler(
    mocker: MockerFixture,
    step_member: ContextProgramsSyncStep | ContextGeoSyncStep | ContextAuroraSyncStep,
    handler_path: str,
    delta_sync: bool,
) -> None:
    fake_return = {"marker": f"{step_member.name}-{delta_sync}"}
    handler_path = f"country_workspace.contrib.{handler_path}"
    mock_fn = mocker.patch(handler_path, return_value=fake_return)

    config = {
        "step_handler": {
            "path": f"{step_member.__class__.__module__}.{step_member.__class__.__qualname__}",
            "name": step_member.name,
        },
        "sync_handler": handler_path,
        "delta_sync": delta_sync,
    }

    result = run_sync(config)
    assert result is fake_return

    mock_fn.assert_called_once_with(delta_sync=delta_sync, step=step_member)
