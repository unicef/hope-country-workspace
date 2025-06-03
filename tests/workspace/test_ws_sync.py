from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from pytest_mock import MockerFixture
from testutils.factories import SyncLogFactory, FieldDefinitionFactory

from country_workspace.models import SyncLog

if TYPE_CHECKING:
    from hope_flex_fields.models import FieldDefinition


@pytest.mark.django_db
def test_sync_log_refresh_no_content_object():
    content_type = ContentType.objects.get_for_model(SyncLog)
    sync_log = SyncLogFactory(content_type=content_type, object_id=None, last_update_date=None)

    sync_log.save()
    sync_log.refresh()

    assert sync_log.last_update_date is None


@pytest.mark.django_db
def test_sync_log_refresh_no_remote_url():
    field_def = FieldDefinitionFactory()
    sync_log = SyncLogFactory(content_object=field_def, data={}, last_update_date=None)

    sync_log.save()
    sync_log.refresh()

    assert sync_log.last_update_date is None


@pytest.mark.django_db
def test_sync_log_refresh_success(mocker: MockerFixture):
    field_def: "FieldDefinition" = FieldDefinitionFactory()

    field_def.attrs = {}
    field_def.save()

    sync_log = SyncLogFactory(content_object=field_def, data={"remote_url": "lookups/test"})

    mock_client = mocker.patch("country_workspace.models.sync.HopeClient")
    mock_instance = mock_client.return_value
    mock_instance.get_lookup.return_value = {"key1": "value1", "key2": "value2"}

    before_update = timezone.now()
    sync_log.refresh()

    field_def.refresh_from_db()
    assert field_def.attrs.get("choices") == [["key1", "value1"], ["key2", "value2"]]
    assert sync_log.last_update_date > before_update
    mock_instance.get_lookup.assert_called_once_with("lookups/test")


@pytest.mark.django_db
def test_sync_log_refresh_existing_attrs(mocker: MockerFixture):
    field_def: "FieldDefinition" = FieldDefinitionFactory()
    field_def.attrs = {"existing": "data"}
    field_def.save()

    sync_log = SyncLogFactory(content_object=field_def, data={"remote_url": "lookups/test"})

    mock_client = mocker.patch("country_workspace.models.sync.HopeClient")
    mock_instance = mock_client.return_value
    mock_instance.get_lookup.return_value = {"key1": "value1"}

    sync_log.refresh()

    field_def.refresh_from_db()
    assert "existing" in field_def.attrs
    assert field_def.attrs["existing"] == "data"
    assert field_def.attrs.get("choices") == [["key1", "value1"]]
    mock_instance.get_lookup.assert_called_once_with("lookups/test")


@pytest.mark.django_db
def test_sync_log_refresh_none_attrs(mocker: MockerFixture):
    mock_field_def = MagicMock()
    mock_field_def.attrs = None
    mock_field_def.pk = 1
    mock_field_def.id = 1
    saved_attrs = None

    def mock_save(*args, **kwargs):
        nonlocal saved_attrs
        saved_attrs = mock_field_def.attrs

    mock_field_def.save.side_effect = mock_save

    field_def = FieldDefinitionFactory()
    sync_log = SyncLogFactory(content_object=field_def)
    sync_log.data = {"remote_url": "lookups/test"}
    sync_log.save()

    mocker.patch("django.contrib.contenttypes.fields.GenericForeignKey.__get__", return_value=mock_field_def)
    mocker.patch("hope_flex_fields.models.FlexField.objects.filter", return_value=[])

    mock_client = mocker.patch("country_workspace.models.sync.HopeClient")
    mock_instance = mock_client.return_value
    mock_instance.get_lookup.return_value = {"key1": "value1"}

    sync_log.refresh()

    assert isinstance(saved_attrs, dict)
    assert "choices" in saved_attrs

    choices = [list(choice) if isinstance(choice, tuple) else choice for choice in saved_attrs["choices"]]
    assert choices == [["key1", "value1"]]
    mock_instance.get_lookup.assert_called_once_with("lookups/test")


@pytest.mark.django_db
def test_sync_manager_refresh():
    SyncLogFactory.create_batch(3)

    sync_logs = SyncLog.objects.all()
    for sync_log in sync_logs:
        assert sync_log.last_update_date is not None


@pytest.mark.django_db
def test_sync_manager_create_lookups(mocker: MockerFixture):
    test_hh_lookups = ["TEST_HH_1", "TEST_HH_2"]
    test_ind_lookups = ["TEST_IND_1"]
    mocker.patch.object(settings, "HH_LOOKUPS", test_hh_lookups)
    mocker.patch.object(settings, "IND_LOOKUPS", test_ind_lookups)

    mock_field_def = MagicMock()
    mock_field_def.pk = 1
    mock_get_field_def = mocker.patch(
        "hope_flex_fields.models.FieldDefinition.objects.get", return_value=mock_field_def
    )

    content_type = ContentType.objects.get_or_create(app_label="hope_flex_fields", model="fielddefinition")[0]

    SyncLog.objects.create_lookups()

    expected_calls = [call(name=f"HOPE HH {lookup}") for lookup in test_hh_lookups] + [
        call(name=f"HOPE IND {lookup}") for lookup in test_ind_lookups
    ]
    assert mock_get_field_def.call_args_list == expected_calls

    sync_logs = SyncLog.objects.all()
    assert sync_logs.count() == len(test_hh_lookups) + len(test_ind_lookups)

    for lookup in test_hh_lookups:
        assert SyncLog.objects.filter(
            content_type=content_type, object_id=mock_field_def.pk, data={"remote_url": f"lookups/{lookup.lower()}"}
        ).exists()

    for lookup in test_ind_lookups:
        assert SyncLog.objects.filter(
            content_type=content_type, object_id=mock_field_def.pk, data={"remote_url": f"lookups/{lookup.lower()}"}
        ).exists()


@pytest.mark.django_db
def test_sync_manager_register_sync(mocker: MockerFixture):
    test_model = MagicMock()
    content_type = ContentType.objects.create(app_label="test_app", model="test_model")
    mocker.patch("django.contrib.contenttypes.models.ContentType.objects.get_for_model", return_value=content_type)

    before_update = timezone.now()
    SyncLog.objects.register_sync(test_model)

    sync_log = SyncLog.objects.get(content_type=content_type)
    assert sync_log.last_update_date > before_update

    new_update_time = timezone.now()
    SyncLog.objects.register_sync(test_model)

    sync_log.refresh_from_db()
    assert sync_log.last_update_date > new_update_time
