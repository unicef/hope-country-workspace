from typing import Any

import factory
from django.contrib.contenttypes.models import ContentType
from hope_smart_export.exporters import ExportAsText
from hope_smart_export.models import Category, Configuration
from strategy_field.utils import fqn

from testutils.factories import AutoRegisterModelFactory


class CategoryFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"Category {n}")

    class Meta:
        model = Category
        django_get_or_create = ["name"]


class ConfigurationFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"Config {n}")
    code = factory.Sequence(lambda n: f"code-{n}")
    content_type = factory.Iterator(ContentType.objects.all())
    exporter = fqn(ExportAsText)

    class Meta:
        model = Configuration

    @factory.post_generation  # type: ignore[misc]
    def categories(self, create: bool, extracted: list[str], **kwargs: Any) -> None:
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            for name in extracted:
                self.categories.add(CategoryFactory(name=name))
