import logging
from typing import Any, Optional

from django.forms import ChoiceField, HiddenInput, Textarea, TextInput
from django.template import Context, Template
from django.utils.safestring import SafeString, mark_safe

from constance import config

logger = logging.getLogger(__name__)


class ObfuscatedInput(HiddenInput):

    def render(
        self, name: str, value: Any, attrs: Optional[dict[str, str]] = None, renderer: Optional[Any] = None
    ) -> "SafeString":
        context = self.get_context(name, value, attrs)
        context["value"] = str(value)
        context["label"] = "Set" if value else "Not Set"

        tpl = Template('<input type="hidden" name="{{ widget.name }}" value="{{ value }}">{{ label }}')
        return mark_safe(tpl.render(Context(context)))  # nosec B308 B703


class WriteOnlyWidget:
    def format_value(self, value: Any) -> str:
        return super().format_value("***")

    def value_from_datadict(self, data: dict[str, Any], files: Any, name: str) -> Any:
        value = data.get(name)
        if value == "***":
            return getattr(config, name)
        return value


class WriteOnlyTextarea(WriteOnlyWidget, Textarea):
    pass


class WriteOnlyInput(WriteOnlyWidget, TextInput):
    pass


class GroupChoiceField(ChoiceField):
    def __init__(self, **kwargs: Any) -> None:
        from django.contrib.auth.models import Group

        ret: list[tuple[str | int, str]] = []
        for c in Group.objects.values("pk", "name"):
            ret.append((c["name"], c["name"]))
        kwargs["choices"] = ret
        super().__init__(**kwargs)
