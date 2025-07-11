from typing import Mapping, Protocol, TypeVar
from country_workspace.models import Household, Individual

T_Beneficiary = TypeVar("T_Beneficiary", bound=Individual | Household)

type BeneficiaryMapping = Mapping[int, T_Beneficiary]


class ValidateBeneficiaries(Protocol):
    def __call__(self, mapping: BeneficiaryMapping) -> None: ...
