from typing import Final, NamedTuple


class HouseholdRoleRefFields(NamedTuple):
    head_of_household: str
    primary_collector: str
    alternate_collector: str


HOUSEHOLD_ROLE_REF_FIELDS: Final[HouseholdRoleRefFields] = HouseholdRoleRefFields(
    head_of_household="head_of_household_id",
    primary_collector="primary_collector_id",
    alternate_collector="alternate_collector_id",
)
