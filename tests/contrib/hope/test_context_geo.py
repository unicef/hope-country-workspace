from unittest.mock import Mock
import pytest
from pytest_mock import MockerFixture
from mptt.exceptions import InvalidMove
from uuid import uuid4

from country_workspace.contrib.hope.sync.base import LogLevel
from country_workspace.contrib.hope.sync.context_geo import SyncContextGeo, SyncStep, sync_context_geo

COUNTRY = {
    "results": [
        {
            "id": str(uuid4()),
            "name": "Ukraine",
            "iso_code2": "UA",
            "iso_code3": "UKR",
        },
    ],
}

AREATYPE = {
    "results": [
        {
            "id": str(uuid4()),
            "name": "UA52",
            "country": "UA",
            "area_level": 1,
        },
    ],
}

AREA = {
    "results": [
        {
            "id": str(uuid4()),
            "name": "Kyivska",
            "p_code": "UA32",
            "area_type": str(uuid4()),
        }
    ],
}


def test_assign_parents_success(mock_model: Mock, mocker: MockerFixture) -> None:
    child_instance = Mock()
    parent_instance = Mock()
    mock_model.objects.get.side_effect = [child_instance, parent_instance]
    mock_model.objects.bulk_update = Mock()

    sync_context = SyncContextGeo(client=mocker.Mock(), stdout=mocker.Mock())

    parent_mapping = {"1": "2"}
    sync_context._assign_parents(mock_model, parent_mapping)

    assert child_instance.parent == parent_instance
    mock_model.objects.bulk_update.assert_called_once_with([child_instance], fields=["parent"])


@pytest.mark.parametrize(
    ("get_side_effect", "error_message"),
    [
        ([Exception("DoesNotExist"), Mock()], "test_model: child '1' not found for parent assignment"),
        ([Mock(), Exception("DoesNotExist")], "test_model parent '2' not found for assignment"),
    ],
    ids=["missing_child", "missing_parent"],
)
def test_assign_parents_missing(mock_model: Mock, mocker: MockerFixture, get_side_effect, error_message) -> None:
    mock_model.DoesNotExist = Exception
    mock_model.objects.get.side_effect = get_side_effect
    mocker.patch.object(SyncContextGeo, "emit_log")

    sync_context = SyncContextGeo(client=mocker.Mock(), stdout=mocker.Mock())
    sync_context._assign_parents(mock_model, {"1": "2"})

    sync_context.emit_log.assert_called_once_with(
        "RECORD_SKIPPED",
        hope_id="1",
        error=error_message,
    )
    assert not hasattr(mock_model.objects, "bulk_update") or not mock_model.objects.bulk_update.called


def test_assign_parents_invalid_move(mock_model: Mock, mocker: MockerFixture) -> None:
    child_instance = Mock()
    parent_instance = Mock()
    mock_model.objects.get.side_effect = [child_instance, parent_instance]
    mock_model.objects.bulk_update.side_effect = InvalidMove("Invalid tree move")
    mocker.patch.object(SyncContextGeo, "emit_log")

    sync_context = SyncContextGeo(client=mocker.Mock(), stdout=mocker.Mock())

    parent_mapping = {"1": "2"}
    sync_context._assign_parents(mock_model, parent_mapping)

    mock_model._meta.model_name = "test_model"
    sync_context.emit_log.assert_called_once_with(
        "RECORD_SYNC_FAILURE",
        LogLevel.ERROR,
        hope_id="multiple",
        error="Invalid MPTT move during bulk update for 'test_model': Invalid tree move",
    )


def test_sync_context_geo_step(mock_model: Mock, mocker: MockerFixture) -> None:
    mocker.patch.object(SyncContextGeo, "sync_countries")
    result = sync_context_geo(step=SyncStep.COUNTRIES, stdout=mocker.Mock())
    SyncContextGeo.sync_countries.assert_called_once()
    assert isinstance(result, dict)
