import factory
from faker import Faker

from country_workspace.models import Individual
from country_workspace.workspaces.models import CountryIndividual

from .base import AutoRegisterModelFactory
from .household import HouseholdFactory
from .office import OfficeFactory
from .program import ProgramFactory

fake = Faker()


class IndividualFlexFieldFactory(factory.DictFactory):
    @classmethod
    def _generate(cls, create, attrs):
        from country_workspace.models import Relationship

        from .lookups import RelationshipFactory

        RelationshipFactory()
        return {
            "relationship_i_c": Relationship.objects.order_by("?").first().code,
            "full_name_i_c": "",
            "given_name_i_c": "",
            "middle_name_i_c": "",
            "family_name_i_c": "",
            "photo_i_c": "",
            "gender_i_c": "",
            "birth_date_i_c": "",
            "estimated_birth_date_i_c": "",
            "national_id_photo_i_c": "",
            "national_id_issuer_i_c": "",
            "phone_no_i_c": "",
            "primary_collector_id": "",
            "alternate_collector_id": "",
        }


class IndividualFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    program = factory.SubFactory(ProgramFactory)
    household = factory.SubFactory(HouseholdFactory)
    full_name = factory.Sequence(lambda n: f"Individual {n}")
    flex_fields = IndividualFlexFieldFactory()

    class Meta:
        model = Individual
        django_get_or_create = ("full_name",)


class CountryIndividualFactory(IndividualFactory):

    class Meta:
        model = CountryIndividual
        django_get_or_create = ("full_name",)
