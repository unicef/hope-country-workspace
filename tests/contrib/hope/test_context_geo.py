from unittest.mock import Mock
from datetime import datetime, timezone, timedelta
import pytest
from pytest_mock import MockerFixture
from mptt.exceptions import InvalidMove
from uuid import uuid4

from country_workspace.contrib.hope.sync.base import SkipRecordError, ParamDateName
from country_workspace.contrib.hope.sync.context_geo import sync_countries, sync_area_types, sync_areas, _assign_parents
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


def _assert_params(delta_sync: bool, config: dict, modified_after: str) -> None:
    params = {"format": "json"}
    if delta_sync:
        assert config["endpoint"].get("params") == {ParamDateName.UPDATED.value: modified_after, **params}
    else:
        assert config["endpoint"].get("params") == params


def test_sync_countries(mocker: MockerFixture, delta_sync: bool) -> None:
    sync_entity_mock = mocker.patch("country_workspace.contrib.hope.sync.context_geo.sync_entity")
    mocker.patch(
        "country_workspace.contrib.hope.sync.base._get_last_updated_date", return_value=COUNTRY["updated_at_after"]
    )

    sync_countries(delta_sync=delta_sync)

    sync_entity_mock.assert_called_once()
    config = sync_entity_mock.call_args.args[0]
    assert config["model"] is Country
    assert config["endpoint"]["path"] == COUNTRY["path"]
    _assert_params(delta_sync, config, COUNTRY["updated_at_after"])

    expected_defaults = {k: COUNTRY["results"][0][k] for k in ("name", "iso_code2", "iso_code3")}
    defaults = config["prepare_defaults"](COUNTRY["results"][0])
    assert defaults == expected_defaults


@pytest.mark.parametrize("expect_error", [False, True], ids=["Country-Exist", "Country-DoesNotExist"])
def test_sync_area_types(mocker: MockerFixture, delta_sync: bool, expect_error: bool) -> None:
    sync_entity_mock = mocker.patch("country_workspace.contrib.hope.sync.context_geo.sync_entity")
    assign_parents_mock = mocker.patch("country_workspace.contrib.hope.sync.context_geo._assign_parents")
    rebuild_mock = mocker.patch.object(AreaType.objects, "rebuild")
    mocker.patch(
        "country_workspace.contrib.hope.sync.base._get_last_updated_date", return_value=AREA_TYPES["updated_at_after"]
    )

    if expect_error:
        mock_country = mocker.patch.object(Country.objects, "get", side_effect=Country.DoesNotExist)
    else:
        mock_country = mocker.patch.object(Country.objects, "get", return_value=object())

    sync_area_types()

    sync_entity_mock.assert_called_once()
    cfg = sync_entity_mock.call_args[0][0]
    rec = AREA_TYPES["results"][0]

    if expect_error:
        with pytest.raises(SkipRecordError, match=r"Country not found."):
            cfg["prepare_defaults"](rec)
    else:
        expected = {
            "country": mock_country.return_value,
            **{k: rec[k] for k in ("name", "area_level", "valid_from", "valid_until", "extras")},
        }
        assert cfg["prepare_defaults"](rec) == expected

        assign_parents_mock.assert_called_once_with(AreaType, {rec["id"]: rec["parent"]})
        rebuild_mock.assert_called_once()


@pytest.mark.parametrize("expect_error", [False, True], ids=["AreaType-Exist", "AreaType-DoesNotExist"])
def test_sync_areas(mocker: MockerFixture, delta_sync: bool, expect_error: bool) -> None:
    sync_entity_mock = mocker.patch("country_workspace.contrib.hope.sync.context_geo.sync_entity")
    assign_parents_mock = mocker.patch("country_workspace.contrib.hope.sync.context_geo._assign_parents")
    rebuild_mock = mocker.patch.object(Area.objects, "rebuild")
    mocker.patch(
        "country_workspace.contrib.hope.sync.base._get_last_updated_date", return_value=AREA_TYPES["updated_at_after"]
    )

    if expect_error:
        mocker.patch.object(AreaType.objects, "get", side_effect=AreaType.DoesNotExist)
    else:
        mock_area_type = mocker.patch.object(AreaType.objects, "get", return_value=object())

    sync_areas(delta_sync)

    sync_entity_mock.assert_called_once()
    cfg = sync_entity_mock.call_args[0][0]
    rec = AREAS["results"][0]

    if expect_error:
        with pytest.raises(SkipRecordError, match=r"AreaType not found."):
            cfg["prepare_defaults"](rec)
    else:
        expected = {
            "area_type": mock_area_type.return_value,
            **{k: rec[k] for k in ("name", "p_code", "valid_from", "valid_until", "extras")},
        }
        assert cfg["prepare_defaults"](rec) == expected
        assign_parents_mock.assert_called_once_with(Area, {rec["id"]: rec["parent"]})
        rebuild_mock.assert_called_once()


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

    format_msg_mock = mocker.patch("country_workspace.contrib.hope.sync.context_geo.format_msg")

    _assign_parents(mock_model, mapping)

    assert m_bulk.call_count == expected_bulk_calls
    keys = [call.args[0] for call in format_msg_mock.call_args_list]
    assert keys == expected_logs
