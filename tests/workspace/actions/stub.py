from typing import Final

header_base: Final[tuple[str, ...]] = ["id", "version"]
header_add: Final[dict[str, tuple[str, ...]]] = {
    "hh": ["admin1", "admin2"],
    "ind": [
        "birth_date",
        "disability",
        "first_registration_date",
        "gender",
        "given_name",
        "relationship",
        "role",
    ],
}
header_last: Final[tuple[str, ...]] = ["is_valid", "errors"]

batch_name: Final[str] = "TestBatch"
batch_size: Final[int] = 10
