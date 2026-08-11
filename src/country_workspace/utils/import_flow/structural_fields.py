import logging
from typing import Any, Final

from django.utils.translation import gettext_lazy as _

from country_workspace.models.household import RELATIONSHIP_NON_BENEFICIARY

logger = logging.getLogger(__name__)

#: Flex fields that define an Individual's structural links: household membership
#: (relationship), household role refs (role) and collector links (collector_id).
#: Household role refs and collector_id links are derived from these fields, so
#: changing them after the links were created would leave stale references.
STRUCTURAL_FIELDS: Final[tuple[str, ...]] = ("relationship", "role", "collector_id")

STRUCTURAL_FIELD_LOCK_ERROR = _(
    "Changes to structural field(s) %(fields)s are not allowed: the record is an "
    "external collector shared program-wide, or the change would turn a member into "
    "one. Collector and household links are managed during import."
)


def _is_external_collector(flex_fields: dict[str, Any]) -> bool:
    """Whether the record is a program-wide external collector.

    Relies on the invariant ``household IS NULL <=> relationship == NON_BENEFICIARY``:
    external collectors are created with ``household=None`` and linked to households
    only through the primary/alternate collector role refs.
    """
    return flex_fields.get("relationship") == RELATIONSHIP_NON_BENEFICIARY


def find_locked_field_changes(current_fields: dict[str, Any], new_fields: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Return structural field changes that must be blocked to keep links valid.

    An external collector is shared program-wide and referenced by other households,
    so its structural fields are frozen. A regular member may change ``role`` and
    ``collector_id`` (household refs and collector links are re-derived from them),
    but turning a member into an external collector is blocked: the member's
    household links would not be rebuilt.
    """
    collector = _is_external_collector(current_fields)
    changes: dict[str, tuple[Any, Any]] = {}
    for field in STRUCTURAL_FIELDS:
        old, new = current_fields.get(field), new_fields.get(field)
        if old == new:
            continue
        if collector or (field == "relationship" and new == RELATIONSHIP_NON_BENEFICIARY):
            changes[field] = (old, new)
    return changes


def enforce_locked_fields(owner: Any, current_fields: dict[str, Any], new_fields: dict[str, Any]) -> dict[str, Any]:
    """Return ``new_fields`` with locked structural changes reverted to current values."""
    changes = find_locked_field_changes(current_fields, new_fields)
    if not changes:
        return new_fields
    logger.warning("Blocked structural field changes on %s: %s", owner, changes)
    result = dict(new_fields)
    for field, (old, _new) in changes.items():
        if field in current_fields:
            result[field] = old
        else:
            result.pop(field, None)
    return result
