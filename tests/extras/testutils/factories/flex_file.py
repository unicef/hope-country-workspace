import factory
from django.contrib.contenttypes.models import ContentType

from country_workspace.models import FlexFieldFile

from .base import AutoRegisterModelFactory
from .individual import IndividualFactory


class FlexFieldFileFactory(AutoRegisterModelFactory):
    class Params:
        record = factory.SubFactory(IndividualFactory)

    content_type = factory.LazyAttribute(lambda o: ContentType.objects.get_for_model(o.record, for_concrete_model=True))
    object_id = factory.LazyAttribute(lambda o: o.record.pk)
    field_name = "photo"
    content = b"file-content"
    mimetype = "application/octet-stream"
    size = factory.LazyAttribute(lambda o: len(o.content))
    original_filename = "file.bin"
    checksum = factory.Sequence(lambda n: f"{n:064x}")

    class Meta:
        model = FlexFieldFile
