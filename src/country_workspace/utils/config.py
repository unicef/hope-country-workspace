from typing import TypedDict
from country_workspace.workspaces.admin.forms import ValidateMode


class BatchNameConfig(TypedDict):
    batch_name: str


class ValidateModeConfig(TypedDict):
    validate_mode: ValidateMode
