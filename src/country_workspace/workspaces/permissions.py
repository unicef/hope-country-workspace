from functools import partial
from typing import Callable, Any

from django.http import HttpRequest


def has_perm_in_office(request: HttpRequest, obj: Any, permission: str, handler: Callable | None = None) -> bool:
    return request.user.has_perm(permission, obj)


can_change_country_program = partial(has_perm_in_office, permission="workspaces.change_countryprogram")
can_import_program_data = partial(has_perm_in_office, permission="country_workspace.import_program_data")
can_debug_async_job = partial(has_perm_in_office, permission="country_workspace.debug_job")
can_reprocess_batch = partial(has_perm_in_office, permission="country_workspace.reprocess_batch")
can_trigger_deduplication = partial(has_perm_in_office, permission="country_workspace.push_beneficiary_to_hope")
