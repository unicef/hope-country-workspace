import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.context_aurora import sync_projects, sync_registrations
from country_workspace.contrib.aurora.models import Project, Registration
from country_workspace.contrib.hope.sync.base import SkipRecordError, ParamDateName

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


@pytest.fixture(
    params=[
        pytest.param(True, id="delta_sync_true"),
        pytest.param(False, id="delta_sync_false"),
    ]
)
def delta_sync(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def aurora_client(mocker: MockerFixture) -> AuroraClient:
    return mocker.Mock(spec=AuroraClient)


def test_sync_projects(mocker: MockerFixture, delta_sync: bool) -> None:
    sync_entity_mock = mocker.patch("country_workspace.contrib.aurora.context_aurora.sync_entity")
    mocker.patch(
        "country_workspace.contrib.hope.sync.base._get_last_updated_date", return_value=PROJECT["modified_after"]
    )

    sync_projects(delta_sync)

    sync_entity_mock.assert_called_once()
    config = sync_entity_mock.call_args.args[0]
    assert config["model"] is Project
    assert config["endpoint"]["path"] == PROJECT["path"]
    _assert_params(delta_sync, config, PROJECT["modified_after"])

    expected_defaults = {k: PROJECT["results"][0][k] for k in ("name",)}
    defaults = config["prepare_defaults"](PROJECT["results"][0])
    assert defaults == expected_defaults


@pytest.mark.parametrize("expect_error", [False, True], ids=["Project-Exist", "Project-DoesNotExist"])
def test_sync_registrations(mocker: MockerFixture, delta_sync: bool, expect_error: bool) -> None:
    sync_entity_mock = mocker.patch("country_workspace.contrib.aurora.context_aurora.sync_entity")
    mocker.patch(
        "country_workspace.contrib.hope.sync.base._get_last_updated_date", return_value=REGISTRATION["modified_after"]
    )

    if expect_error:
        mock_project = mocker.patch.object(Project.objects, "get", side_effect=Project.DoesNotExist)
    else:
        mock_project = mocker.patch.object(Project.objects, "get", return_value=object())

    sync_registrations(delta_sync)
    sync_entity_mock.assert_called_once()

    config = sync_entity_mock.call_args.args[0]
    assert config["model"] is Registration
    assert config["endpoint"]["path"] == REGISTRATION["path"]
    _assert_params(delta_sync, config, REGISTRATION["modified_after"])

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


def test_prepare_defaults_registration_invalid_url(mocker: MockerFixture) -> None:
    sync_entity_mock = mocker.patch("country_workspace.contrib.aurora.context_aurora.sync_entity")
    mocker.patch(
        "country_workspace.contrib.hope.sync.base._get_last_updated_date", return_value=PROJECT["modified_after"]
    )

    sync_registrations()

    config = sync_entity_mock.call_args.args[0]
    bad_rec = {
        **REGISTRATION["results"][0],
        "project": "not-a-valid-url",
    }

    with pytest.raises(SkipRecordError, match="Invalid project URL format."):
        config["prepare_defaults"](bad_rec)


def _assert_params(delta_sync: bool, config: dict, modified_after: str) -> None:
    params = {"format": "json"}
    if delta_sync:
        assert config["endpoint"].get("params") == {ParamDateName.MODIFIED.value: modified_after, **params}
    else:
        assert config["endpoint"].get("params") == params
