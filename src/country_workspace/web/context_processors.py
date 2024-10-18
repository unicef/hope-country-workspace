from typing import Any

from django.http import HttpRequest

from country_workspace import VERSION
from country_workspace.state import state


def current_state(request: HttpRequest) -> dict[str, Any]:
    ret = {"state": state, "app": {"version": VERSION}}
    return ret
