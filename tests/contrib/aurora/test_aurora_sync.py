import re
from contextlib import nullcontext
from typing import Generator

import pytest
import responses
from constance import config
from django.core.cache import cache
from pytest_mock import MockerFixture

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.models import Project
from country_workspace.contrib.aurora.sync import (
    sync_all,
    sync_projects,
    sync_registrations,
)
from country_workspace.models import SyncLog
from tests.contrib.aurora import stub


@pytest.fixture
def cache_setup_and_fake_lock(mocker: MockerFixture) -> Generator[None, None, None]:
    cache.clear()
    patcher = mocker.patch(
        "country_workspace.contrib.aurora.sync.cache.lock",
        return_value=nullcontext(),
    )
    yield patcher
    cache.clear()


@pytest.fixture(autouse=True)
def clear_sync_logs(force_migrated_records) -> Generator[None, None, None]:
    SyncLog.objects.all().delete()
    yield
    SyncLog.objects.all().delete()


@pytest.fixture
def project(force_migrated_records) -> Project:
    from testutils.factories import ProjectFactory

    return ProjectFactory(reference_pk=1, name="Default Project")


@pytest.fixture
def job():
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory()


@pytest.mark.xdist_group("remote")
def test_sync_all(
    mocker: MockerFixture,
    mocked_responses: responses.RequestsMock,
    cache_setup_and_fake_lock,
) -> None:
    expected_programs = {"add": 0, "upd": 0}
    expected_projects = {"add": 1, "upd": 1}
    expected_registrations = {"add": 1, "upd": 3}

    with (
        mocker.patch("country_workspace.contrib.aurora.sync.sync_programs", return_value=expected_programs),
        mocker.patch("country_workspace.contrib.aurora.sync.sync_projects", return_value=expected_projects),
        mocker.patch("country_workspace.contrib.aurora.sync.sync_registrations", return_value=expected_registrations),
    ):
        totals = sync_all(job=job)

    assert totals == {
        "programs": expected_programs,
        "projects": expected_projects,
        "registrations": expected_registrations,
    }
    cache_setup_and_fake_lock.assert_called_once_with("sync-aurora")


def test_sync_projects(
    mocker: MockerFixture,
    mocked_responses: responses.RequestsMock,
    project: Project,
    clear_sync_logs,
) -> None:
    # NOTE: This test is linked to the stub data in `tests/contrib/aurora/stub.py`
    """The stub data contains 2 records:
    - A project with id=6 and name "Lanka Project #1" - will be created,
    - A project with id=1 and name "Default Project" - will be updated.
    """
    expected = {"add": 1, "upd": 1}
    mocked_responses.add(
        responses.GET,
        re.compile(re.escape(config.AURORA_API_URL) + ".*"),
        json=stub.project,
        status=200,
    )

    totals = sync_projects(client=AuroraClient())

    assert totals == expected
    assert Project.objects.count() == 2
    assert SyncLog.objects.count() == 1


def test_sync_registrations(
    mocker: MockerFixture,
    mocked_responses: responses.RequestsMock,
    project: Project,
    clear_sync_logs,
) -> None:
    # NOTE: This test is linked to the stub data in `tests/contrib/aurora/stub.py`
    """The stub data contains 5 records:
    - Record with id=1: valid registration for project 1 (will be created),
    - Record with id=2: invalid URL (will be skipped),
    - Record with id=3: valid registration for project 1 (will be created),
    - Record with id=4: reference to a non-existent project (will be skipped),
    - Record with id=1: duplicate registration for project 1 (will be updated).
    """
    expected = {"add": 2, "upd": 1, "skip": [2, 4]}
    mocked_responses.add(
        responses.GET,
        re.compile(re.escape(config.AURORA_API_URL) + ".*"),
        json=stub.registration,
        status=200,
    )

    totals = sync_registrations(client=AuroraClient())

    assert totals == expected
    assert Project.objects.count() == 1
    assert project.registrations.count() == 2
    assert SyncLog.objects.count() == 1
