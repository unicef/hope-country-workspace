from random import getrandbits, randint

from django.utils import timezone

import factory
from faker import Faker

from country_workspace.models import Household
from country_workspace.workspaces.models import CountryHousehold

from .base import AutoRegisterModelFactory
from .office import OfficeFactory
from .program import ProgramFactory

fake = Faker()


class HouseholdFlexFieldFactory(factory.DictFactory):
    @classmethod
    def _generate(cls, create, attrs):
        return {
            "consent_h_c": bool(getrandbits(1)),
            "country_origin_h_c": "",
            "country_h_c": "",
            "admin1_h_c": "",
            "admin2_h_c": "",
            "size_h_c": randint(1, 5),
            "hh_latrine_h_f": bool(getrandbits(1)),
            "hh_electricity_h_f": bool(getrandbits(1)),
            "registration_method_h_c": "",
            "collect_individual_data_h_c": "",
            "name_enumerator_h_c": fake.name(),
            "org_enumerator_h_c": "",
            "consent_sharing_h_c": "",
            "first_registration_date_h_c": str(timezone.now().date()),
        }


class HouseholdFactory(AutoRegisterModelFactory):
    country_office = factory.SubFactory(OfficeFactory)
    program = factory.SubFactory(ProgramFactory)
    name = factory.Faker("last_name")
    flex_fields = HouseholdFlexFieldFactory()

    class Meta:
        model = Household
        django_get_or_create = ("name",)

    @factory.post_generation
    def individuals(self, create, extracted, **kwargs):
        from .individual import IndividualFactory

        for i in range(self.flex_fields["size_h_c"]):
            IndividualFactory(
                country_office=self.country_office,
                program=self.program,
                household=self,
            )


class CountryHouseholdFactory(HouseholdFactory):
    class Meta:
        model = CountryHousehold
        django_get_or_create = ("name",)
