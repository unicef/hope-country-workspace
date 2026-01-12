import logging
from typing import Any, Mapping

from constance import config
from django.conf import settings
from django.forms import ChoiceField, HiddenInput, TextInput, Textarea
from django.template import Context, Template
from django.utils.safestring import SafeString, mark_safe

logger = logging.getLogger(__name__)


class ObfuscatedInput(HiddenInput):
    def render(
        self,
        name: str,
        value: Any,
        attrs: dict[str, str] | None = None,
        renderer: Any | None = None,
    ) -> "SafeString":
        context = self.get_context(name, value, attrs)
        context["value"] = str(value)
        context["label"] = "Set" if value else "Not Set"

        tpl = Template('<input type="hidden" name="{{ widget.name }}" value="{{ value }}">{{ label }}')
        return mark_safe(tpl.render(Context(context)))  # noqa: S308


class GroupChoiceField(ChoiceField):
    def __init__(self, **kwargs: Any) -> None:
        from django.contrib.auth.models import Group

        ret: list[tuple[str | int, str]] = [(c["name"], c["name"]) for c in Group.objects.values("pk", "name")]
        kwargs["choices"] = ret
        super().__init__(**kwargs)


class WriteOnlyMixin:
    """Write-only widget mixin that never renders stored secrets into HTML."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.mask = getattr(settings, "CONSTANCE_DEFAULTS_MASK", "***")
        self.attrs.setdefault("placeholder", self.mask)
        self.attrs.setdefault("autocomplete", "new-password")
        self.attrs.setdefault("spellcheck", "false")

    def format_value(self, value: Any) -> str:
        return ""

    def value_from_datadict(self, data: Mapping[str, Any], files: Any, name: str) -> Any:
        if (value := data.get(name) or "") == "":
            return getattr(config, name)

        if value.strip() == self.mask:
            default_value, *_ = settings.CONSTANCE_CONFIG[name]
            return default_value

        return value


class WriteOnlyTextInput(WriteOnlyMixin, TextInput): ...


class WriteOnlyTextarea(WriteOnlyMixin, Textarea): ...
