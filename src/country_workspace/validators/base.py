from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold


class BeneficiaryGroupValidator:
    def __init__(self, program):
        pass

    def validate(self, hh: "CountryHousehold") -> bool:
        pass
