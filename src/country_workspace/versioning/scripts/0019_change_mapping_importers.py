from packaging.version import Version
from django.db import transaction
from country_workspace.contrib.hope.constants import (
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)

_script_for_version = Version("0.1.0")

OLD = "gender_to_sex"
RENAME = {
    INDIVIDUAL_CHECKER_NAME: "individual_rules",
    PEOPLE_CHECKER_NAME: "people_rules",
}

IND_RULES_ADD = (
    "national_id_no=national_id_document_number",
    "national_id_issuer=national_id_country",
    "national_id_photo=national_id_image",
)

HH_RULES = (
    "head_of_household_id=head_of_household",
    "primary_collector_id=primary_collector",
    "alternate_collector_id=alternate_collector",
)

_lines = lambda s: [x for x in map(str.strip, s.splitlines()) if x]


def merge_rules(text: str, extra: tuple[str, ...] | list[str]) -> str:
    cur = _lines(text)
    cur_set = set(cur)
    cur.extend(r for r in extra if r not in cur_set)
    return "\n".join(cur)


@transaction.atomic
def forward() -> None:
    pass


@transaction.atomic
def backward() -> None:
    pass


class Scripts:
    requires = []
    operations = [(forward, backward)]
