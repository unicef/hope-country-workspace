from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest
from django.db.models import Q
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.sync.base import (
    SyncConfig,
    EndpointConfig,
    sync_entity,
    log_to,
    Stats,
)

from tests.extras.testutils.utils import assert_stdout_contains


@pytest.fixture
def hope_client(mocker: MockerFixture) -> HopeClient:
    return mocker.Mock(spec=HopeClient)


@pytest.fixture(params=[True, False])
def delta_sync(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def out(mocker: MockerFixture) -> Mock:
    return mocker.Mock()


@pytest.fixture
def mock_model(mocker: MockerFixture) -> Mock:
    model = mocker.Mock()
    model.DoesNotExist = type("DoesNotExist", (Exception,), {})
    model._meta = mocker.Mock()
    model._meta.model_name = "test_model"
    return model


@pytest.fixture
def records() -> list[dict[str, Any]]:
    return [
        {"id": "1", "value": "test", "active": True},  # Active record
        {"id": "2", "active": False},  # Inactive record
        {"name": "no_id"},  # Missing ID
    ]


@pytest.fixture
def success_config(mock_model: Mock) -> SyncConfig:
    return SyncConfig(
        model=mock_model,
        reference_id="reference_id",
        endpoint=EndpointConfig(path="dummy_path"),
        prepare_defaults=lambda r: {"key": r.get("value")},
        should_process=lambda r: r.get("active"),
    )


@pytest.fixture
def deactivate_config(mock_model: Mock) -> SyncConfig:
    return SyncConfig(
        model=mock_model,
        endpoint=EndpointConfig(path="dummy_path"),
        prepare_defaults=lambda r: {"key": r.get("value")},
        should_deactivate=lambda r: not r.get("active"),
    )


@pytest.fixture(autouse=True)
def mock_synclog(mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.models.SyncLog.objects.register_sync")


@pytest.fixture
def deactivate_filter() -> Q:
    return Q(active=True) & (~Q(hope_id__in={"1"}) | Q(hope_id__in={"2"}))


@pytest.fixture
def sync_entity_context(hope_client: HopeClient, out: Mock) -> Callable[[list[dict], SyncConfig], Stats]:
    def _run_sync_entity(records: list[dict], config: SyncConfig) -> Stats:
        hope_client.get.return_value = iter(records)
        stats = Stats(add=0, upd=0, errors=[])
        with log_to(out):
            stats = sync_entity(config, hope_client, stats)
        assert_stdout_contains(out, "Start fetching 'test_model'", "Sync complete for 'test_model'")
        return stats

    return _run_sync_entity
