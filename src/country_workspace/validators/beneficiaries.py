from typing import Mapping
from country_workspace.workspaces.exceptions import BeneficiaryValidationError
from country_workspace.utils.types import T_Beneficiary

from country_workspace.utils.config import FailIfAlienConfig


def validate_beneficiaries(config: FailIfAlienConfig, beneficiary_mapping: Mapping[int, T_Beneficiary]) -> None:
    if config.get("check_before", False):
        for key, beneficiary in beneficiary_mapping.items():
            if not beneficiary.validate_with_checker(fail_if_alien=config.get("fail_if_alien", False)):
                raise BeneficiaryValidationError(beneficiary._meta.object_name, key)
