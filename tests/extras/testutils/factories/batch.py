from django.utils import timezone

import factory

from country_workspace.models.batch import Batch

from .base import AutoRegisterModelFactory
from .user import UserFactory


class BatchFactory(AutoRegisterModelFactory):
    imported_by = factory.SubFactory(UserFactory)
    import_date = factory.LazyFunction(timezone.now)
    label = factory.Sequence(lambda n: f"Batch {n}")

    class Meta:
        model = Batch
