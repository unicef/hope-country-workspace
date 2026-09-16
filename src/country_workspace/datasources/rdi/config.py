from collections.abc import Iterable
from enum import StrEnum
from typing import NotRequired

from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.fields import Record


Sheet = Iterable[Record]


class Config(BatchNameConfig, ValidateModeConfig):
    master_detail: bool
    beneficiary_id_column: str
    household_id_column: NotRequired[str]
    household_label: NotRequired[str]
    people_prefix: NotRequired[str]
    first_line: int
    household_mapping_id: NotRequired[int | None]
    individual_mapping_id: NotRequired[int | None]
    household_transformer_id: NotRequired[int | None]
    individual_transformer_id: NotRequired[int | None]


class SheetName(StrEnum):
    HOUSEHOLDS = "Households"
    INDIVIDUALS = "Individuals"
    PEOPLE = "People"
