import factory
import factory.fuzzy

from country_workspace.contrib.aurora.models import Project, Registration
from .program import ProgramFactory


class ProjectFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Project {n}")
    reference_pk = factory.fuzzy.FuzzyInteger(100)
    program = factory.SubFactory(ProgramFactory)

    class Meta:
        model = Project
        django_get_or_create = ("name",)


class RegistrationFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Registration {n}")
    active = factory.fuzzy.FuzzyChoice([True, False])
    reference_pk = factory.fuzzy.FuzzyInteger(100)
    project = factory.SubFactory(ProjectFactory)

    class Meta:
        model = Registration
        django_get_or_create = ("name",)
