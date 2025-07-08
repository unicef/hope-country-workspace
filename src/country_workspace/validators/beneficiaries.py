from typing import Mapping
from country_workspace.workspaces.exceptions import BeneficiaryValidationError
from country_workspace.utils.types import T_Beneficiary

from country_workspace.utils.config import ValidateModeConfig
from country_workspace.workspaces.admin.forms import ValidateMode


def validate_beneficiaries(config: ValidateModeConfig, beneficiary_mapping: Mapping[int, T_Beneficiary]) -> None:
    mode = ValidateMode(config["validate_mode"])
    if mode is ValidateMode.NONE:
        return

    fail_if_alien = mode is ValidateMode.CHECK_AND_FAIL_IF_ALIEN
    for key, beneficiary in beneficiary_mapping.items():
        if not beneficiary.validate_with_checker(fail_if_alien=fail_if_alien):
            raise BeneficiaryValidationError(beneficiary._meta.object_name, key)
