from typing import TYPE_CHECKING, Any, Callable

import pytest
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse
from pytest_mock import MockerFixture
from unittest.mock import MagicMock

from country_workspace.admin.sync import (
    SyncAdminMixin,
    Target,
    TargetArgs,
    TargetConfig,
    SyncAdminConfig,
    run_sync,
    task,
    can_sync,
)
from country_workspace.admin import sync as sync_module

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp
    from django.db.models import Model
    from country_workspace.models import User


@pytest.fixture
def admin_request(admin_user) -> Any:
    req = RequestFactory().get("/admin/x/")
    req.user = admin_user
    return req


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.fixture
def sync_admin_case(request: pytest.FixtureRequest) -> tuple[type["Model"], str]:
    from country_workspace.contrib.aurora.models import Project
    from country_workspace.models import Office, Program, Country, AreaType, Area

    cases: dict[str, tuple[type[Model], str]] = {
        "Office": (Office, "country_workspace"),
        "Program": (Program, "country_workspace"),
        "Country": (Country, "country_workspace"),
        "AreaType": (AreaType, "country_workspace"),
        "Area": (Area, "country_workspace"),
        "Project": (Project, "aurora"),
    }
    return cases[request.param]


@pytest.fixture
def delta_result_success(sync_admin_case: tuple[type["Model"], str]) -> dict[str, dict[str, Any]]:
    model, _ = sync_admin_case
    name = model._meta.model_name
    return {name: {"add": 1, "upd": 2, "errors": []}}


@pytest.fixture
def delta_result_error(sync_admin_case: tuple[type["Model"], str]) -> dict[str, dict[str, Any]]:
    model, _ = sync_admin_case
    name = model._meta.model_name
    return {name: {"add": 0, "upd": 0, "errors": [f"Error 1 for {name}", f"Error 2 for {name}"]}}


@pytest.fixture
def button_handler() -> MagicMock:
    """
    Minimal ButtonHandler stub: admin_extra_buttons passes handler=<ButtonHandler ...>
    which exposes .model_admin and .get_instance().
    """
    h = MagicMock()
    h.model_admin = None
    h.get_instance.return_value = None
    return h


@pytest.fixture
def job_factory() -> Callable[..., Any]:
    def _make(*, targets: list[dict[str, Any]] | None, has_perm: bool) -> Any:
        job = MagicMock()
        job.config = {"targets": targets} if targets is not None else {}
        job.owner = MagicMock()
        job.owner.has_perm = MagicMock(return_value=has_perm)
        return job

    return _make


@pytest.fixture
def run_sync_case(request: pytest.FixtureRequest) -> tuple[list[TargetConfig], dict[Target, dict[str, Any]]]:
    if request.param == "no_args":
        return [TargetConfig(target=Target.OFFICES)], {Target.OFFICES: {}}

    if request.param == "with_args":
        return (
            [
                TargetConfig(target=Target.OFFICES, args=TargetArgs(delta_sync=True)),
                TargetConfig(target=Target.PROGRAMS, args=TargetArgs(delta_sync=True, office_id=123)),
            ],
            {
                Target.OFFICES: {"delta_sync": True},
                Target.PROGRAMS: {"delta_sync": True, "office_id": 123},
            },
        )

    raise AssertionError(f"Unknown case: {request.param}")


def test_can_sync_returns_false_when_admin_model_is_none(admin_request: Any, button_handler: MagicMock) -> None:
    assert can_sync(admin_request, None, handler=button_handler) is False


def test_require_sync_perms_raises_when_missing_any_perm(
    mocker: MockerFixture,
    admin_request: Any,
) -> None:
    admin = mocker.Mock(spec=SyncAdminMixin)
    admin.sync_config = SyncAdminConfig(targets=[TargetConfig(target=Target.OFFICES)])

    mocker.patch(
        "country_workspace.admin.sync.required_perms_from_targets",
        return_value=["p1", "p2"],
    )
    admin_request.user.has_perm = MagicMock(side_effect=[True, False])

    with pytest.raises(PermissionDenied):
        SyncAdminMixin._require_sync_perms(admin, admin_request)


@pytest.mark.parametrize(
    "sync_admin_case",
    ["Office", "Program", "Country", "AreaType", "Area", "Project"],
    ids=["Office", "Program", "Country", "AreaType", "Area", "Project"],
    indirect=True,
)
def test_admin_sync_full_schedules_job(
    app: "CWTestApp",
    mocker: MockerFixture,
    sync_admin_case: tuple["type[Model]", str],
) -> None:
    model, admin_app = sync_admin_case
    url = reverse(f"admin:{admin_app}_{model._meta.model_name}_sync")

    job = MagicMock()
    create_job = mocker.patch("country_workspace.admin.sync.AsyncJob.objects.create", return_value=job)
    mock_run = mocker.patch("country_workspace.admin.sync.run_sync")
    mock_msg = mocker.patch.object(SyncAdminMixin, "message_user")

    resp = app.get(url)

    assert resp.status_code == 302
    create_job.assert_called_once()
    job.queue.assert_called_once()
    mock_run.assert_not_called()
    mock_msg.assert_called_once_with(mocker.ANY, "Synchronization is scheduled.", level=messages.SUCCESS)


@pytest.mark.parametrize(
    "sync_admin_case",
    ["Office", "Program", "Country", "AreaType", "Area", "Project"],
    ids=["Office", "Program", "Country", "AreaType", "Area", "Project"],
    indirect=True,
)
@pytest.mark.parametrize(
    "scenario",
    ["success", "error"],
    ids=["success", "error"],
)
def test_admin_sync_delta_runs_and_messages(
    app: "CWTestApp",
    mocker: MockerFixture,
    sync_admin_case: tuple["type[Model]", str],
    scenario: str,
    delta_result_success: dict[str, dict[str, Any]],
    delta_result_error: dict[str, dict[str, Any]],
) -> None:
    model, admin_app = sync_admin_case
    name = model._meta.model_name
    url = reverse(f"admin:{admin_app}_{name}_sync_delta")

    result = delta_result_success if scenario == "success" else delta_result_error
    mock_run = mocker.patch("country_workspace.admin.sync.run_sync", return_value=result)
    mock_msg = mocker.patch.object(SyncAdminMixin, "message_user")

    resp = app.get(url)

    assert resp.status_code == 302
    mock_run.assert_called_once()
    cfg = mock_run.call_args.kwargs["config"]
    assert all(t.get("args", {}).get("delta_sync") is True for t in cfg["targets"])

    expected_text = (
        f"{name}: 1 created - 2 updated" if scenario == "success" else f"Error 1 for {name} | Error 2 for {name}"
    )
    expected_level = messages.SUCCESS if scenario == "success" else messages.ERROR
    mock_msg.assert_called_once_with(mocker.ANY, expected_text, level=expected_level)


@pytest.mark.parametrize(
    "run_sync_case",
    ["no_args", "with_args"],
    ids=["no-args-default-empty-dict", "args-forwarded-to-handler"],
    indirect=True,
)
def test_run_sync_imports_handlers_calls_them_and_collects_stats(
    mocker: MockerFixture,
    run_sync_case: tuple[list[TargetConfig], dict[Target, dict[str, Any]]],
) -> None:
    targets, expected_calls = run_sync_case

    handlers: dict[str, MagicMock] = {}

    def fake_import_string(path: str) -> Any:
        handlers.setdefault(path, MagicMock(return_value={"add": 1, "upd": 0, "errors": []}))
        return handlers[path]

    import_mock = mocker.patch("country_workspace.admin.sync.import_string", side_effect=fake_import_string)

    stats = run_sync(config=SyncAdminConfig(targets=targets))

    assert import_mock.call_count == len(targets)

    for tcfg in targets:
        target = tcfg["target"]
        handler_path = sync_module.TARGET_TO_HANDLER_PATH_MAPPING[target]
        handlers[handler_path].assert_called_once_with(**expected_calls[target])
        assert stats[target] == {"add": 1, "upd": 0, "errors": []}


@pytest.mark.parametrize(
    ("targets", "has_perm", "expected_raises"),
    [
        ([], True, True),  # empty targets -> perms == [] -> denied
        ([{"target": Target.OFFICES}], False, True),  # missing perm -> denied
        ([{"target": Target.OFFICES}], True, False),  # ok -> run_sync called
    ],
    ids=["empty-targets", "missing-perm", "ok"],
)
def test_task_permission_gate(
    mocker: MockerFixture,
    job_factory: Any,
    targets: list[dict[str, Any]],
    has_perm: bool,
    expected_raises: bool,
) -> None:
    mocker.patch(
        "country_workspace.admin.sync.required_perms_from_targets",
        return_value=["country_workspace.sync_office"] if targets else [],
    )
    run = mocker.patch("country_workspace.admin.sync.run_sync", return_value={"x": "y"})
    job = job_factory(targets=targets, has_perm=has_perm)

    if expected_raises:
        with pytest.raises(PermissionDenied):
            task(job)
        run.assert_not_called()
    else:
        assert task(job) == {"x": "y"}
        run.assert_called_once_with(config=job.config)
