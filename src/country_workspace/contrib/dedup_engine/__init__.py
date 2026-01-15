from typing import Any
from collections.abc import Mapping

from country_workspace.models import AsyncJob


def dedup(job: AsyncJob) -> Mapping[str, Any]:
    return {"status": "stubbed"}


def dedup_was_successful(rdp_id: int) -> bool:
    return True
