from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.workspaces.admin import program as program_admin_mod


@pytest.fixture
def country_office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def dedup_settings_data() -> dict[str, dict[str, float | str]]:
    return {
        "settings": {
            "threshold_1": 0.1,
            "threshold_2": 0.2,
            "threshold_3": 0.3,
        },
        "post_data": {
            "threshold_1": "0.11",
            "threshold_2": "0.22",
            "threshold_3": "0.33",
        },
        "payload": {
            "threshold_1": 0.11,
            "threshold_2": 0.22,
            "threshold_3": 0.33,
        },
    }


@pytest.fixture
def mock_dedup_settings_policy(mocker: MockerFixture) -> Callable[..., MagicMock]:
    def factory(
        *,
        allowed: bool = True,
        visible: bool = True,
        reason: str | None = None,
    ) -> MagicMock:
        policy = mocker.MagicMock()
        policy.is_update_dedup_settings_visible.return_value = visible
        policy.update_dedup_settings_check.return_value = ActionCheck(allowed, reason)

        mocker.patch.object(
            program_admin_mod,
            "get_program_dedup_settings_policy",
            return_value=policy,
        )
        return policy

    return factory


@pytest.fixture
def mock_dedup_client(mocker: MockerFixture) -> tuple[MagicMock, MagicMock]:
    client = mocker.MagicMock()
    context_manager = mocker.MagicMock()
    context_manager.__enter__.return_value = client
    context_manager.__exit__.return_value = False

    make_client = mocker.patch.object(
        program_admin_mod,
        "make_dedup_client",
        return_value=context_manager,
    )
    return make_client, client
