import factory

from country_workspace.models import BeneficiaryGroup, Program
from country_workspace.workspaces.models import CountryProgram

from .base import AutoRegisterModelFactory
from .office import OfficeFactory
from .serializer import DataSerializerFactory
from .smart_import import DataCheckerFactory


class BeneficiaryGroupFactory(AutoRegisterModelFactory):
    hope_id = factory.Sequence(lambda n: f"beneficiary_group-{n}")
    name = factory.Sequence(lambda n: f"Beneficiary Group {n}")
    group_label = factory.Faker("word")
    group_label_plural = factory.LazyAttribute(lambda obj: f"{obj.group_label}s")
    member_label = factory.Faker("word")
    member_label_plural = factory.LazyAttribute(lambda obj: f"{obj.member_label}s")
    master_detail = factory.fuzzy.FuzzyChoice([True, False])

    class Meta:
        model = BeneficiaryGroup
        django_get_or_create = ("name",)


class ProgramFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    hope_id = factory.Sequence(lambda n: f"program-{n}")
    name = factory.Sequence(lambda n: f"Program {n}")
    code = factory.Sequence(lambda n: f"{n:04d}")
    household_checker = factory.SubFactory(DataCheckerFactory)
    individual_checker = factory.SubFactory(DataCheckerFactory)
    beneficiary_group = factory.SubFactory(BeneficiaryGroupFactory)
    serializer = factory.SubFactory(DataSerializerFactory)

    class Meta:
        model = Program
        django_get_or_create = ("name",)


class CountryProgramFactory(ProgramFactory):
    class Meta:
        model = CountryProgram
        django_get_or_create = ("name",)
