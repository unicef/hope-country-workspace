import logging
from typing import Any

from django.forms import ChoiceField

logger = logging.getLogger(__name__)


class GroupSelect(ChoiceField):
    def __init__(self, **kwargs: Any) -> None:
        from django.contrib.auth.models import Group

        ret: list[tuple[str | int, str]] = []
        for c in Group.objects.values("pk", "name"):
            ret.append((c["name"], c["name"]))
        kwargs["choices"] = ret
        super().__init__(**kwargs)
