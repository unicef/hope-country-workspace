from typing import Any

from django import forms
from django.forms.widgets import Select


class SelectWithEmptyOption(Select):
    empty_label = "None"

    def __init__(self, attrs: dict[str, Any] | None = None, choices: tuple = (), empty_label: Any = None) -> None:
        super().__init__(attrs, choices)
        if empty_label is not None:
            self.empty_label = empty_label

    def optgroups(self, name: str, value: list[str], attrs: dict[str, Any] | None = None) -> Any:
        groups = super().optgroups(name, value, attrs)

        has_empty = any(opt.get("value") in ("", None) for _, group_choices, _ in groups for opt in group_choices)

        if not has_empty:
            empty_option = self.create_option(
                name=name,
                value="",
                label=self.empty_label,
                selected=(value == "" or value is None),
                index=0,
                attrs=attrs,
            )

            empty_group = (None, [empty_option], 0)
            groups = [empty_group] + groups

        return groups


class ChoiceFieldWithEmptyDisplay(forms.ChoiceField):
    widget = SelectWithEmptyOption
