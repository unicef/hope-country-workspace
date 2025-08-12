from typing import TYPE_CHECKING
from country_workspace.validators.base import BeneficiaryGroupValidator

if TYPE_CHECKING:
    from country_workspace.models import Household


class FullHouseholdValidator(BeneficiaryGroupValidator):
    def validate(self, hh: "Household") -> list:
        errs = []
        if not (head_id := hh.head()):
            errs.append("This Household does not have Head")

        if not (primary_id := hh.primary_collector()):
            errs.append("This Household does not have Primary Collector")

        if primary_id and (alternate_id := hh.alternate_collector()) and primary_id == alternate_id:
            errs.append("Primary collector and Alternate collectors can not be the same")

        if head_id and not hh.members.filter(id=head_id).exists():
            errs.append("Household Head must be from the given Household")

        return errs
