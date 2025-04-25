from typing import TypeVar
from country_workspace.models import Household, Individual

T_Beneficiary = TypeVar("T_Beneficiary", bound=Individual | Household)
