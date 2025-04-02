from collections.abc import Mapping, Hashable
from typing import Any

from django.template import Library


register = Library()


@register.filter(name="get_item")
def get_item(dictionary: Mapping[Any, Any] | None, key: Hashable) -> Any | None:
    if isinstance(dictionary, Mapping):
        return dictionary.get(key)
    return None
