import factory
import factory.fuzzy

from country_workspace.models import Registration
from .office import OfficeFactory
from .program import ProgramFactory


class RegistrationFactory(factory.django.DjangoModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    program = factory.SubFactory(ProgramFactory)
    name = factory.Sequence(lambda n: f"Registration {n}")
    reference_pk = factory.fuzzy.FuzzyInteger(100)

    class Meta:
        model = Registration
        django_get_or_create = ("name",)
