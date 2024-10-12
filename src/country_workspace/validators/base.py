from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from country_workspace.models import Household, Program


class BeneficiaryGroupValidator:
    def __init__(self, program: "Program"):
        self.program = program

    def validate(self, hh: "Household") -> bool:
        return True
