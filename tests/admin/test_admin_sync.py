from typing import TYPE_CHECKING

import pytest
from django.contrib import messages
from django.db.models import Model
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.admin.sync import (
    SyncAdminMixin,
    run_sync,
    Target,
    TARGET_TO_HANDLER_PATH_MAPPING,
    SyncAdminConfig,
    TargetConfig,
    TargetArgs,
)
from country_workspace.contrib.aurora.models import Project
from country_workspace.models import Office, Program, Country, AreaType, Area

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
        (Project, "aurora"),
    ],
    ids=["Office", "Program", "Country", "AreaType", "Area", "Project"],
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
    result = {
        model._meta.model_name: {"add": 1, "upd": 2, "errors": []}
        if scenario == "success"
        else {
            "add": 0,
            "upd": 0,
            "errors": [f"Error 1 for {model._meta.model_name}", f"Error 2 for {model._meta.model_name}"],
        }
    }
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
            f"{model._meta.model_name}: 1 created - 2 updated"
            if scenario == "success"
            else f"Error 1 for {model._meta.model_name} | Error 2 for {model._meta.model_name}"
        )
    )
    expected_level = messages.SUCCESS if not delta_sync or scenario == "success" else messages.ERROR

    response = app.get(reverse(url_name))

    assert response.status_code == 302
    mock_run.assert_called_once()
    cfg = mock_run.call_args.kwargs["config"]
    assert all(target.get("args", {}).get("delta_sync", False) is delta_sync for target in cfg["targets"])
    mock_msg.assert_called_once_with(mocker.ANY, expected_text, level=expected_level)


@pytest.mark.parametrize(
    "target",
    [
        Target.OFFICES,
        Target.BENEFICIARY_GROUPS,
        Target.PROGRAMS,
        Target.COUNTRIES,
        Target.AREA_TYPES,
        Target.AREAS,
        Target.PROJECTS,
        Target.REGISTRATIONS,
    ],
)
@pytest.mark.parametrize("delta_sync", [False, True], ids=["full", "delta"])
def test_run_sync_invokes_correct_handler(
    mocker: MockerFixture,
    target: Target,
    delta_sync: bool,
) -> None:
    handler_path = TARGET_TO_HANDLER_PATH_MAPPING[target]
    handler_mock = mocker.patch(handler_path)

    result = run_sync(
        SyncAdminConfig(
            targets=[
                TargetConfig(target=target, args=TargetArgs(delta_sync=delta_sync)),
            ]
        )
    )
    assert len(result) == 1
    assert list(result.values()) == [handler_mock.return_value]

    handler_mock.assert_called_once_with(delta_sync=delta_sync)
