from random import choice

import factory
from faker import Faker

from country_workspace.models import Individual
from country_workspace.workspaces.models import CountryIndividual

from .base import AutoRegisterModelFactory
from .household import HouseholdFactory

fake = Faker()


def get_ind_fields(individual: "CountryIndividual"):
    return {
        "alternate_collector_id": "",
        "birth_date": "",
        "disability": "",
        "estimated_birth_date": "",
        "family_name": individual.household.name,
        "full_name": "%s %s" % (individual.name, individual.household.name),
        "gender": choice(["MALE", "FEMALE"]),
        "given_name": "",
        "household_id": individual.household.flex_fields["household_id"],
        "middle_name": "",
        "national_id_issuer": "",
        "national_id_photo": "",
        "phone_no": "",
        "photo": "",
        "primary_collector_id": "",
        "relationship": choice(["HEAD", "SON_DAUGHTER", "BROTHER_SISTER", "FOSTER_CHILD"]),
    }


class IndividualFactory(AutoRegisterModelFactory):
    # batch = factory.SubFactory(BatchFactory)
    # country_office = factory.SubFactory(OfficeFactory)
    # program = factory.SubFactory(ProgramFactory)
    household = factory.SubFactory(HouseholdFactory)
    name = factory.LazyAttribute(lambda o: "%s %s" % (fake.first_name(), o.household.name))
    flex_fields = factory.LazyAttribute(get_ind_fields)

    class Meta:
        model = Individual
        django_get_or_create = ("name",)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        if "household" in kwargs:
            kwargs["batch"] = kwargs["household"].batch
        # kwargs["batch"] = kwargs["household"].batch
        # kwargs["country_office"] = kwargs["household"].country_office
        # kwargs["program"] = kwargs["household"].program
        return super()._create(model_class, *args, **kwargs)


class CountryIndividualFactory(IndividualFactory):
    class Meta:
        model = CountryIndividual
        django_get_or_create = ("name",)
