from typing import TypedDict


class BatchNameConfig(TypedDict):
    batch_name: str


class CheckBeforeConfig(TypedDict):
    check_before: bool


class FailIfAlienConfig(CheckBeforeConfig):
    fail_if_alien: bool
