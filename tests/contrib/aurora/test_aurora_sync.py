import pytest
import responses
import re

from typing import Generator, Any

from contextlib import nullcontext

from django.core.cache import cache
from pytest_mock import MockerFixture
from country_workspace.contrib.aurora.sync import (
    sync_projects,
    sync_registrations,
)
from country_workspace.contrib.aurora.models import Project
from country_workspace.models import SyncLog
from constance import config

from tests.contrib.aurora import stub


@pytest.fixture
def cache_setup_and_fake_lock(mocker: MockerFixture) -> Generator[None, None, None]:
    cache.clear()
    mocker.patch(
        "country_workspace.contrib.aurora.sync.cache.lock",
        return_value=nullcontext(),
    )
    yield
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


# Fixture that creates an existing registration when limit_provided is True.
@pytest.fixture
def existing_registration(project, limit_provided: bool) -> None:
    if limit_provided:
        from testutils.factories import RegistrationFactory

        RegistrationFactory(
            project=project,
            reference_pk=101,
            name="Registration 101",
            active=True,
        )


def test_sync_projects(
    mocker: MockerFixture,
    mocked_responses: responses.RequestsMock,
    project: Project,
    clear_sync_logs,
    cache_setup_and_fake_lock,
) -> None:
    # NOTE: This test is linked to the stub data in `tests/contrib/aurora/stub.py`
    expected = {"add": 1, "upd": 1}
    mocked_responses.add(
        responses.GET,
        re.compile(re.escape(config.AURORA_API_URL) + ".*"),
        json=stub.project.get("correct", {}),
        status=200,
    )

    totals = sync_projects()

    assert totals == expected
    assert Project.objects.count() == 2
    assert SyncLog.objects.count() == 1


@pytest.mark.parametrize(
    ("limit_provided", "stub_data", "expected_totals", "expected_regs"),
    [
        # When limit_to_project is provided:
        # - An existing registration with id 101 is created (will be updated)
        # - The API stub returns 2 registrations for the project: id 101 and id 102.
        # Expected: {"add": 1, "upd": 1, "skip": 0} and the project should have 2 registrations.
        (True, stub.registration["with_limit"], {"add": 1, "upd": 1, "skip": 0}, 2),
        # When limit_to_project is not provided:
        # - The API stub returns 3 registrations:
        #   * Registration with id 201 is valid (will be created),
        #   * Registration with id 202 has an invalid URL (skipped),
        #   * Registration with id 203 refers to a non-existent project (skipped).
        # Expected: {"add": 1, "upd": 0, "skip": 2} and total registrations across projects should be 1.
        (False, stub.registration["without_limit"], {"add": 1, "upd": 0, "skip": 2}, 1),
    ],
)
@pytest.mark.django_db
def test_sync_registrations(
    mocked_responses: responses.RequestsMock,
    mocker: MockerFixture,
    project: Project,
    existing_registration,
    clear_sync_logs,
    cache_setup_and_fake_lock,
    limit_provided: bool,
    stub_data: Any,
    expected_totals: dict[str, int],
    expected_regs: int,
) -> None:
    # NOTE: This test is linked to the stub data in `tests/contrib/aurora/stub.py`
    mocked_responses.add(
        responses.GET,
        re.compile(re.escape(config.AURORA_API_URL) + ".*"),
        json=stub_data,
        status=200,
    )
    totals = sync_registrations(limit_to_project=project if limit_provided else None)
    assert totals == expected_totals

    if limit_provided:
        assert project.registrations.count() == expected_regs
    else:
        total_regs = sum(p.registrations.count() for p in Project.objects.all())
        assert total_regs == expected_regs

    assert SyncLog.objects.count() == 1
