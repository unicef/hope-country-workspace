from unittest.mock import Mock
from datetime import datetime, timezone, timedelta
import pytest
from pytest_mock import MockerFixture
from mptt.exceptions import InvalidMove
from uuid import uuid4
from io import StringIO

from country_workspace.contrib.hope.sync.base import BaseSync, SkipRecordError, ParamDateName
from country_workspace.contrib.hope.sync.context_geo import SyncContextGeo, SyncStep, sync_context_geo
from country_workspace.models import Country, AreaType, Area

_today = datetime.now(timezone.utc).date()

COUNTRY = {
    "path": "lookups/country",
    "updated_at_after": "2025-05-05",
    "results": [
        {
            "id": str(uuid4()),
            "name": "Testland Example",
            "iso_code2": "TL",
            "iso_code3": "TLD",
            "short_name": "Testland",
        },
    ],
}

AREA_TYPES = {
    "path": "areatypes",
    "updated_at_after": "2025-05-05",
    "results": [
        {
            "id": str(uuid4()),
            "name": "RegionExample",
            "country": "country-hope-id",
            "parent": "parent-hope-id",
            "area_level": 2,
            "valid_from": (_today - timedelta(days=30)).isoformat(),
            "valid_until": (_today + timedelta(days=30)).isoformat(),
            "extras": {"foo": "bar"},
        },
    ],
}


AREAS = {
    "path": "areas",
    "updated_at_after": "2025-05-05",
    "results": [
        {
            "id": str(uuid4()),
            "name": "AreaExample",
            "area_type": "areatype-hope-id",
            "parent": "parent-area-id",
            "p_code": "P001",
            "valid_from": (_today - timedelta(days=30)).isoformat(),
            "valid_until": (_today + timedelta(days=30)).isoformat(),
            "extras": {"x": "y"},
        },
    ],
}


@pytest.fixture
def sync_geo(base_sync: BaseSync) -> SyncContextGeo:
    return SyncContextGeo(delta_sync=base_sync.delta_sync, client=base_sync.client, stdout=base_sync.stdout)


def test_sync_countries(mocker: MockerFixture, sync_geo: SyncContextGeo) -> None:
    mock_sync_entity = mocker.patch.object(sync_geo, "sync_entity")
    mocker.patch.object(sync_geo, "_get_last_updated_date", return_value=COUNTRY["updated_at_after"])

    sync_geo.sync_countries()

    mock_sync_entity.assert_called_once()
    config = mock_sync_entity.call_args.args[0]
    assert config["model"] is Country
    assert config["endpoint"]["path"] == COUNTRY["path"]
    if sync_geo.delta_sync:
        assert config["endpoint"].get("params") == {ParamDateName.UPDATED.value: COUNTRY["updated_at_after"]}
    else:
        assert config["endpoint"].get("params") is None

    expected_defaults = {k: COUNTRY["results"][0][k] for k in ("name", "iso_code2", "iso_code3")}
    defaults = config["prepare_defaults"](COUNTRY["results"][0])
    assert defaults == expected_defaults


@pytest.mark.parametrize("expect_error", [False, True], ids=["Country-Exist", "Country-DoesNotExist"])
def test_sync_area_types(mocker: MockerFixture, sync_geo: SyncContextGeo, expect_error: bool) -> None:
    mocker.patch.object(sync_geo, "sync_countries")
    m_entity = mocker.patch.object(sync_geo, "sync_entity")
    mocker.patch.object(sync_geo, "_get_last_updated_date", return_value=AREA_TYPES["updated_at_after"])
    m_assign = mocker.patch.object(sync_geo, "_assign_parents")
    m_rebuild = mocker.patch.object(AreaType.objects, "rebuild")

    if expect_error:
        mock_country = mocker.patch.object(Country.objects, "get", side_effect=Country.DoesNotExist)
    else:
        mock_country = mocker.patch.object(Country.objects, "get", return_value=object())

    sync_geo.sync_area_types()

    m_entity.assert_called_once()
    cfg = m_entity.call_args[0][0]
    rec = AREA_TYPES["results"][0]

    if expect_error:
        with pytest.raises(SkipRecordError, match="Country not found."):
            cfg["prepare_defaults"](rec)
    else:
        expected = {
            "country": mock_country.return_value,
            **{k: rec[k] for k in ("name", "area_level", "valid_from", "valid_until", "extras")},
        }
        assert cfg["prepare_defaults"](rec) == expected

        m_assign.assert_called_once_with(AreaType, {rec["id"]: rec["parent"]})
        m_rebuild.assert_called_once()


@pytest.mark.parametrize("expect_error", [False, True], ids=["AreaType-Exist", "AreaType-DoesNotExist"])
def test_sync_areas(mocker: MockerFixture, sync_geo: SyncContextGeo, expect_error: bool) -> None:
    mocker.patch.object(sync_geo, "sync_area_types")
    m_entity = mocker.patch.object(sync_geo, "sync_entity")
    mocker.patch.object(sync_geo, "_get_last_updated_date", return_value=AREAS["updated_at_after"])
    m_assign = mocker.patch.object(sync_geo, "_assign_parents")
    m_rebuild = mocker.patch.object(Area.objects, "rebuild")

    if expect_error:
        mocker.patch.object(AreaType.objects, "get", side_effect=AreaType.DoesNotExist)
    else:
        mock_area_type = mocker.patch.object(AreaType.objects, "get", return_value=object())

    sync_geo.sync_areas()

    m_entity.assert_called_once()
    cfg = m_entity.call_args[0][0]
    rec = AREAS["results"][0]

    if expect_error:
        with pytest.raises(SkipRecordError, match="AreaType not found."):
            cfg["prepare_defaults"](rec)
    else:
        expected = {
            "area_type": mock_area_type.return_value,
            **{k: rec[k] for k in ("name", "p_code", "valid_from", "valid_until", "extras")},
        }
        assert cfg["prepare_defaults"](rec) == expected
        m_assign.assert_called_once_with(Area, {rec["id"]: rec["parent"]})
        m_rebuild.assert_called_once()


@pytest.mark.parametrize(
    ("child_ok", "parent_ok", "bulk_exc", "expected_bulk_calls", "expected_logs"),
    [
        (True, True, False, 1, []),
        (False, True, False, 0, ["RECORD_SKIPPED"]),
        (True, False, False, 0, ["RECORD_SKIPPED"]),
        (True, True, True, 1, ["RECORD_SYNC_FAILURE"]),
    ],
    ids=["success", "missing_child", "missing_parent", "invalid_move"],
)
def test_assign_parents(
    mocker: MockerFixture,
    sync_geo: SyncContextGeo,
    mock_model: Mock,
    child_ok: bool,
    parent_ok: bool,
    bulk_exc: bool,
    expected_bulk_calls: int,
    expected_logs: list[str],
) -> None:
    child_id, parent_id = "c1", "p1"
    mapping = {child_id: parent_id}
    child_inst = mocker.Mock(hope_id=child_id)
    parent_inst = mocker.Mock(hope_id=parent_id)

    def fake_get(*, hope_id):
        instances = {
            **({child_id: child_inst} if child_ok else {}),
            **({parent_id: parent_inst} if parent_ok else {}),
        }
        obj = instances.get(hope_id)
        if obj is None:
            raise mock_model.DoesNotExist
        return obj

    mocker.patch.object(mock_model.objects, "get", side_effect=fake_get)

    m_bulk = mocker.patch.object(mock_model.objects, "bulk_update")
    if bulk_exc:
        m_bulk.side_effect = InvalidMove("boom")

    m_log = mocker.patch.object(sync_geo, "emit_log")

    sync_geo._assign_parents(mock_model, mapping)

    assert m_bulk.call_count == expected_bulk_calls
    keys = [call.args[0] for call in m_log.call_args_list]
    assert keys == expected_logs


@pytest.mark.parametrize("delta_sync", [True, False], ids=["delta_sync_true", "delta_sync_false"])
def test_sync_context_geo_invokes_sync_context(mocker: MockerFixture, delta_sync: bool) -> None:
    fake_result = {"ok": True}
    patch = mocker.patch(
        "country_workspace.contrib.hope.sync.context_geo.sync_context",
        return_value=fake_result,
    )
    stdout = StringIO()

    result = sync_context_geo(delta_sync=delta_sync, step=SyncStep.AREAS, stdout=stdout)

    patch.assert_called_once_with(SyncContextGeo, delta_sync=delta_sync, step=SyncStep.AREAS, stdout=stdout)
    assert result is fake_result
