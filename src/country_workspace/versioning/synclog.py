from django.conf import settings
from django.contrib.contenttypes.models import ContentType

from hope_flex_fields.models import FieldDefinition

from country_workspace.models import SyncLog


def create_default_synclog():
    for m in settings.LOOKUPS:
        fd = FieldDefinition.objects.get(name="HOPE HH {m}".format(m=m))
        ct = ContentType.objects.get_for_model(SyncLog)
        SyncLog.objects.get_or_create(content_type=ct, object_id=fd.id, data={"remote_url": "lookups/%s" % m.lower()})


def removes_default_synclog():
    pass
