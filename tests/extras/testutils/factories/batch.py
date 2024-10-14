from django.utils import timezone

import factory

from country_workspace.models.batch import Batch

from .base import AutoRegisterModelFactory
from .user import UserFactory

# from .office import OfficeFactory
# from .program import ProgramFactory


class BatchFactory(AutoRegisterModelFactory):
    imported_by = factory.SubFactory(UserFactory)
    import_date = factory.LazyFunction(timezone.now)
    name = factory.Sequence(lambda n: f"Batch {n}")

    country_office = factory.SubFactory("testutils.factories.OfficeFactory")
    program = factory.SubFactory("testutils.factories.ProgramFactory")

    class Meta:
        model = Batch
