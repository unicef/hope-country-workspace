from country_workspace.models import Office
from country_workspace.state import state
from country_workspace.utils.config import ValidateModeConfig
from country_workspace.utils.types import BeneficiaryMapping
from country_workspace.workspaces.admin.forms import ValidateMode
from country_workspace.workspaces.exceptions import BeneficiaryValidationError


def validate_beneficiaries(beneficiary_mapping: BeneficiaryMapping, config: ValidateModeConfig, office: Office) -> None:
    mode = ValidateMode(config["validate_mode"])
    if mode is ValidateMode.NONE:
        return

    fail_if_alien = mode is ValidateMode.CHECK_AND_FAIL_IF_ALIEN
    with state.set(tenant=office):
        if error_keys := _collect_validation_errors(beneficiary_mapping, fail_if_alien):
            beneficiary = next(iter(beneficiary_mapping.values()))
            raise BeneficiaryValidationError(beneficiary._meta.object_name, error_keys)


def _collect_validation_errors(beneficiary_mapping: BeneficiaryMapping, fail_if_alien: bool) -> list[int]:
    return [
        key
        for key, beneficiary in beneficiary_mapping.items()
        if not beneficiary.validate_with_checker(fail_if_alien=fail_if_alien)
    ]
