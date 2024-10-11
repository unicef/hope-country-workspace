from strategy_field.registry import Registry

from country_workspace.validators.base import BeneficiaryGroupValidator


class NoopValidator(BeneficiaryGroupValidator):
    pass


beneficiary_validator_registry = Registry(BeneficiaryGroupValidator)

beneficiary_validator_registry.register(NoopValidator)
