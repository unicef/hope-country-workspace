import pytest
from django.contrib.contenttypes.models import ContentType
from country_workspace.contrib.hope.client import HopeClient
from unittest import mock

from testutils.factories import SyncLogFactory, FlexFieldFactory


@pytest.fixture
def sync_log() -> "SyncLogFactory":
    flex = FlexFieldFactory()
    fd = flex.definition
    ct = ContentType.objects.get_for_model(fd)
    return SyncLogFactory(content_type=ct, object_id=fd.pk, data={"remote_url": "http://fake-lookup/"})


@pytest.mark.parametrize(
    ("data", "lookup_ret", "expect_called"),
    [
        ({"remote_url": "http://fake-lookup/"}, {"A": "a", "B": "b"}, True),
        ({}, None, False),
    ],
    ids=["with_url", "no_url"],
)
def test_refresh(sync_log, data, lookup_ret, expect_called):
    sync_log.data = data
    sync_log.save(update_fields=["data"])
    fd = sync_log.content_object
    objs = [fd, *fd.instances.all()]
    old_attrs = [o.attrs.copy() for o in objs]
    old_date = sync_log.last_update_date

    with mock.patch.object(HopeClient, "get_lookup", return_value=lookup_ret) as get_lookup:
        sync_log.refresh()
    if expect_called:
        get_lookup.assert_called_once_with(data["remote_url"])
    else:
        get_lookup.assert_not_called()

    for o in objs:
        o.refresh_from_db()
    sync_log.refresh_from_db()

    if expect_called:
        expected = [[k, v] for k, v in lookup_ret.items()]
        assert all(o.attrs["choices"] == expected for o in objs)
        assert sync_log.last_update_date > old_date
    else:
        assert [o.attrs for o in objs] == old_attrs
        assert sync_log.last_update_date == old_date
