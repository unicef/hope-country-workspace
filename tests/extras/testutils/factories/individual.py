from random import choice

import factory
from faker import Faker

from country_workspace.models import Individual
from country_workspace.workspaces.models import CountryIndividual

from .base import AutoRegisterModelFactory
from .batch import CountryBatchFactory
from .household import HouseholdFactory

fake = Faker()


def get_ind_fields(individual: "CountryIndividual"):
    hh = individual.household
    fname = hh.name if hh else fake.last_name()
    return {
        "birth_date": fake.date_between(start_date="-40y", end_date="-10y").strftime("%Y-%m-%d"),
        "disability": "",
        "estimated_birth_date": "",
        "family_name": fname,
        "full_name": f"{individual.name} {fname}",
        "sex": choice(["MALE", "FEMALE"]),
        "given_name": "",
        "household_id": hh.flex_fields["household_id"] if hh else None,
        "middle_name": "",
        "photo": "",
        "relationship": choice(["HEAD", "SON_DAUGHTER", "BROTHER_SISTER", "FOSTER_CHILD"]),
        "national_id_document_number": "",
        "national_id_image": "",
        "national_id_issuance_date": "",
        "national_id_expiry_date": "",
        "national_id_country": "",
        "national_passport_document_number": "",
        "national_passport_image": "",
        "national_passport_issuance_date": "",
        "national_passport_expiry_date": "",
        "national_passport_country": "",
        "phone_no": "",
        "mobile_financial_institution": "",
        "bank_number": "",
        "bank_financial_institution": "",
    }


class IndividualFactory(AutoRegisterModelFactory):
    household = factory.SubFactory(HouseholdFactory)
    batch = factory.SubFactory(CountryBatchFactory)
    name = factory.LazyAttributeSequence(
        lambda o, n: f"{fake.first_name()} {o.household.name if o.household else fake.last_name()} {n}"
    )
    flex_fields = factory.LazyAttribute(get_ind_fields)

    class Meta:
        model = Individual
        django_get_or_create = ("name",)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        if "household" in kwargs and kwargs["household"] is not None:
            kwargs["batch"] = kwargs["household"].batch
        return super()._create(model_class, *args, **kwargs)

    @factory.post_generation
    def rdps(self, create, extracted, **kwargs):
        """Handle rdp ManyToMany relationship."""
        if not create:
            return
        if extracted:
            if isinstance(extracted, (list, tuple)):
                self.rdp.set(extracted)
            else:
                self.rdp.add(extracted)


class CountryIndividualFactory(IndividualFactory):
    class Meta:
        model = CountryIndividual
        django_get_or_create = ("name",)
