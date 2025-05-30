from collections.abc import Callable
import pytest
from pytest_mock import MockerFixture
from io import StringIO

from country_workspace.contrib.hope.sync.base import BaseSync, SkipRecordError
from country_workspace.contrib.aurora.models import Project, Registration
from country_workspace.contrib.aurora.context_aurora import SyncContextAurora, SyncStep, sync_context_aurora
from country_workspace.contrib.aurora.client import AuroraClient

PROJECT = {
    "path": "project",
    "modified_after": "2025-05-05",
    "results": [
        {
            "id": 1,
            "name": "Test Project",
        },
    ],
}

REGISTRATION = {
    "path": "registration",
    "modified_after": "2025-05-05",
    "results": [
        {
            "id": 1,
            "project": "https://example.com/project/1",
            "name": "Test Registration",
        },
    ],
}


@pytest.fixture
def base_sync(mocker: MockerFixture) -> BaseSync:
    client = mocker.Mock(spec=AuroraClient)
    client.get = mocker.Mock()
    stdout = mocker.Mock()
    return BaseSync(client=client, stdout=stdout)


@pytest.fixture
def sync_aurora(base_sync: BaseSync) -> Callable:
    return SyncContextAurora(client=base_sync.client, stdout=base_sync.stdout)


def test_sync_projects(sync_aurora: SyncContextAurora, mocker: MockerFixture) -> None:
    mock_sync_entity = mocker.patch.object(sync_aurora, "sync_entity")
    mocker.patch.object(sync_aurora, "get_updated_at_after", return_value=PROJECT["modified_after"])

    sync_aurora.sync_projects()

    mock_sync_entity.assert_called_once()
    config = mock_sync_entity.call_args.args[0]
    assert config["model"] is Project
    ep = config["endpoint"]
    assert (ep["path"], ep.get("params")) == (PROJECT["path"], {"modified_after": PROJECT["modified_after"]})

    expected_defaults = {k: PROJECT["results"][0][k] for k in ("name",)}
    defaults = config["prepare_defaults"](PROJECT["results"][0])
    assert defaults == expected_defaults


@pytest.mark.parametrize("expect_error", [False, True], ids=["Project-Exist", "Project-DoesNotExist"])
def test_sync_registrations(sync_aurora: SyncContextAurora, mocker: MockerFixture, expect_error: bool) -> None:
    mocker.patch.object(sync_aurora, "sync_projects")
    mocker.patch.object(sync_aurora, "get_updated_at_after", return_value=REGISTRATION["modified_after"])
    mock_sync_entity = mocker.patch.object(sync_aurora, "sync_entity")
    if expect_error:
        mock_project = mocker.patch.object(Project.objects, "get", side_effect=Project.DoesNotExist)
    else:
        mock_project = mocker.patch.object(Project.objects, "get", return_value=object())

    sync_aurora.sync_registrations()

    mock_sync_entity.assert_called_once()

    config = mock_sync_entity.call_args.args[0]
    assert config["model"] is Registration
    ep = config["endpoint"]
    assert (ep["path"], ep.get("params")) == (REGISTRATION["path"], {"modified_after": REGISTRATION["modified_after"]})

    if expect_error:
        with pytest.raises(SkipRecordError, match="Project not found."):
            config["prepare_defaults"](REGISTRATION["results"][0])
    else:
        expected_defaults = {
            "project": mock_project.return_value,
            "name": REGISTRATION["results"][0]["name"],
            "reference_pk": REGISTRATION["results"][0]["id"],
        }

        defaults = config["prepare_defaults"](REGISTRATION["results"][0])
        assert defaults == expected_defaults


def test_prepare_defaults_registration_invalid_url(sync_aurora: SyncContextAurora, mocker: MockerFixture) -> None:
    mocker.patch.object(sync_aurora, "sync_projects")
    mocker.patch.object(sync_aurora, "get_updated_at_after", return_value=REGISTRATION["modified_after"])
    mock_sync_entity = mocker.patch.object(sync_aurora, "sync_entity")

    sync_aurora.sync_registrations()

    config = mock_sync_entity.call_args.args[0]
    bad_rec = {
        **REGISTRATION["results"][0],
        "project": "not-a-valid-url",
    }

    with pytest.raises(SkipRecordError, match="Invalid project URL format."):
        config["prepare_defaults"](bad_rec)


def test_sync_context_aurora_invokes_sync_context(mocker: MockerFixture) -> None:
    fake_result = {"ok": True}
    patch = mocker.patch(
        "country_workspace.contrib.aurora.context_aurora.sync_context",
        return_value=fake_result,
    )
    stdout = StringIO()

    result = sync_context_aurora(step=SyncStep.REGISTRATIONS, stdout=stdout)

    patch.assert_called_once_with(SyncContextAurora, step=SyncStep.REGISTRATIONS, stdout=stdout)
    assert result is fake_result
