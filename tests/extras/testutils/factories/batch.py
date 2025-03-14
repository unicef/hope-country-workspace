import factory
from django.utils import timezone

from country_workspace.models.batch import Batch
from country_workspace.workspaces.models import CountryBatch

from .base import AutoRegisterModelFactory
from .program import ProgramFactory
from .user import UserFactory


class BatchFactory(AutoRegisterModelFactory):
    imported_by = factory.SubFactory(UserFactory)
    import_date = factory.LazyFunction(timezone.now)
    name = factory.Sequence(lambda n: f"Batch {n}")

    program = factory.SubFactory(ProgramFactory)

    class Meta:
        model = Batch

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        kwargs["country_office"] = kwargs["program"].country_office
        return super()._create(model_class, *args, **kwargs)


class CountryBatchFactory(BatchFactory):
    class Meta:
        model = CountryBatch
        django_get_or_create = ("name",)
