from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from country_workspace.models import Household, Program


class BeneficiaryGroupValidator:
    def __init__(self, program: "Program") -> None:
        self.program = program

    def validate(self, hh: "Household") -> list[str]:
        return []
