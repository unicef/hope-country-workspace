from typing import Callable, Any
from unittest.mock import Mock
import pytest
from django.db.models import Q
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.sync.base import (
    BaseSync,
    SyncConfig,
    BaseSyncStep,
)

from tests.extras.testutils.utils import assert_stdout_contains


@pytest.fixture
def base_sync(mocker: MockerFixture) -> BaseSync:
    client = mocker.Mock()
    client.get = mocker.Mock()
    stdout = mocker.Mock()
    return BaseSync(client=client, stdout=stdout)


@pytest.fixture
def mock_model(mocker: MockerFixture) -> Mock:
    model = mocker.Mock()
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
        path="dummy_path",
        prepare_defaults=lambda r: {"key": r.get("value")},
        should_process=lambda r: r.get("active"),
    )


@pytest.fixture
def deactivate_config(mock_model: Mock) -> SyncConfig:
    return SyncConfig(
        model=mock_model,
        path="dummy_path",
        prepare_defaults=lambda r: {"key": r.get("value")},
        should_deactivate=lambda r: not r.get("active"),
    )


@pytest.fixture(autouse=True)
def mock_synclog(mocker: MockerFixture) -> None:
    mocker.patch("country_workspace.models.SyncLog.objects.register_sync")


@pytest.fixture
def sync_context_class(mocker: MockerFixture) -> type:
    class TestSyncContext(BaseSync):
        SyncStep = [Mock(func=mocker.Mock())]

    return TestSyncContext


@pytest.fixture
def deactivate_filter() -> Q:
    return Q(active=True) & (~Q(hope_id__in={"1"}) | Q(hope_id__in={"2"}))


@pytest.fixture
def sync_step(mocker: MockerFixture) -> BaseSyncStep:
    sync_method = mocker.Mock(spec=Callable[["BaseSync"], None])

    class TestSyncStep(BaseSyncStep):
        TEST_STEP = (1, sync_method)

    return TestSyncStep.TEST_STEP


@pytest.fixture
def sync_entity_context(base_sync: BaseSync) -> Callable:
    def _run_sync_entity(records: list[dict], config: SyncConfig) -> None:
        base_sync.client.get.return_value = iter(records)
        base_sync.sync_entity(config)
        assert_stdout_contains(base_sync.stdout, "Start fetching 'test_model'", "Sync complete for 'test_model'")

    return _run_sync_entity
