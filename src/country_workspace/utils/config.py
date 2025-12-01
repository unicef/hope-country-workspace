from typing import TypedDict, NotRequired


class BatchNameConfig(TypedDict):
    batch_name: str


class ValidateModeConfig(TypedDict):
    validate_after_import: NotRequired[bool]
    fail_if_alien: NotRequired[bool]
