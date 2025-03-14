import sys
from random import getrandbits, randint

import factory
from django.utils import timezone
from faker import Faker

from country_workspace.models import Household
from country_workspace.workspaces.models import CountryHousehold

from .base import AutoRegisterModelFactory
from .batch import CountryBatchFactory

fake = Faker()


def get_hh_fields(household: "CountryHousehold"):
    return {
        "address": fake.street_address(),
        "admin1": "",
        "admin2": "",
        "admin3": "",
        "admin4": "",
        "residence_status": "",
        "collect_individual_data": True,
        "consent": bool(getrandbits(1)),
        "consent_sharing": "",
        "country": fake.country(),
        "country_origin": "",
        "first_registration_date": str(timezone.now().date()),
        "household_id": randint(1, sys.maxsize),
        "name_enumerator": fake.name(),
        "org_enumerator": "",
        "registration_method": "",
        "registration_id": "",
        "size": randint(1, 5),
        "female_age_group_0_5_count": 0,
        "female_age_group_6_11_count": 0,
        "female_age_group_12_17_count": 0,
        "female_age_group_18_59_count": 0,
        "female_age_group_60_count": 0,
        "pregnant_count": 0,
        "male_age_group_0_5_count": 0,
        "male_age_group_6_11_count": 0,
        "male_age_group_12_17_count": 0,
        "male_age_group_18_59_count": 0,
        "male_age_group_60_count": 0,
        "female_age_group_0_5_disabled_count": 0,
        "female_age_group_6_11_disabled_count": 0,
        "female_age_group_12_17_disabled_count": 0,
        "female_age_group_18_59_disabled_count": 0,
        "female_age_group_60_disabled_count": 0,
        "male_age_group_0_5_disabled_count": 0,
        "male_age_group_6_11_disabled_count": 0,
        "male_age_group_12_17_disabled_count": 0,
        "male_age_group_18_59_disabled_count": 0,
        "male_age_group_60_disabled_count": 0,
        "zip_code": fake.zipcode(),
    }


def get_name(instance, num):
    name = fake.last_name()
    return f"{name} #{num}"


class HouseholdFactory(AutoRegisterModelFactory):
    batch = factory.SubFactory(CountryBatchFactory)
    name = factory.LazyAttributeSequence(get_name)

    flex_fields = factory.LazyAttribute(get_hh_fields)

    class Meta:
        model = Household

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return super()._create(model_class, *args, **kwargs)

    @factory.post_generation
    def individuals(self, create, extracted, **kwargs):
        from .individual import IndividualFactory

        if extracted is not None:
            pass
        else:
            self.flex_fields.setdefault("household_id", self.id)
            for __ in range(self.flex_fields["size"]):
                IndividualFactory(batch=self.batch, household=self)


class CountryHouseholdFactory(HouseholdFactory):
    class Meta:
        model = CountryHousehold
        django_get_or_create = ("name",)
