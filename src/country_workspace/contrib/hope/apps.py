from django.apps import AppConfig

from .geo import Admin1Choice, Admin2Choice, Admin3Choice, Admin4Choice, CountryChoice
from .lookups import CurrencyChoice, FinancialInstitutionChoice
from .phone_numbers import PhoneNumberField
from .beneficiary_reference import BeneficiaryReferenceModelChoiceField
from .required_choice_field import ChoiceFieldWithEmptyDisplay


class Config(AppConfig):
    name = __name__.rpartition(".")[0]
    verbose_name = "Country Workspace"

    def ready(self) -> None:
        from hope_flex_fields.attributes.registry import attributes_registry
        from hope_flex_fields.registry import field_registry

        from .remotes.country import CountryAttributeHandler
        from country_workspace.utils.flex_fields import ObservedDisabilityChoice

        attributes_registry.register(CountryAttributeHandler)
        field_registry.register(CountryChoice)
        field_registry.register(CurrencyChoice)
        field_registry.register(Admin1Choice)
        field_registry.register(Admin2Choice)
        field_registry.register(Admin3Choice)
        field_registry.register(Admin4Choice)
        field_registry.register(FinancialInstitutionChoice)
        field_registry.register(PhoneNumberField)
        field_registry.register(BeneficiaryReferenceModelChoiceField)
        field_registry.register(ChoiceFieldWithEmptyDisplay)
        field_registry.register(ObservedDisabilityChoice)

        from country_workspace.contrib.hope.validators import FullHouseholdValidator
        from country_workspace.validators.registry import beneficiary_validator_registry

        beneficiary_validator_registry.register(FullHouseholdValidator)
