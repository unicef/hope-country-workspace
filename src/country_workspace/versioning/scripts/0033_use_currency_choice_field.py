from concurrency.utils import fqn
from django import forms
from django.db import transaction
from hope_flex_fields.models import FieldDefinition, FlexField
from hope_flex_fields.registry import field_registry
from packaging.version import Version

from country_workspace.contrib.hope.lookups import CurrencyChoice

_script_for_version = Version("0.1.0")


def _drop_choices(attrs: dict | None) -> dict:
    cleaned = dict(attrs or {})
    cleaned.pop("choices", None)
    return cleaned


@transaction.atomic()
def forward() -> None:
    field_registry.register(CurrencyChoice)
    for fd in FieldDefinition.objects.filter(name="Currency"):
        fd.field_type = fqn(CurrencyChoice)
        fd.attrs = _drop_choices(fd.attrs)
        fd.save(update_fields=["field_type", "attrs"])
        for ff in FlexField.objects.filter(definition=fd):
            ff.attrs = _drop_choices(ff.attrs)
            ff.save(update_fields=["attrs"])


@transaction.atomic()
def backward() -> None:
    for fd in FieldDefinition.objects.filter(name="Currency"):
        fd.field_type = fqn(forms.ChoiceField)
        fd.attrs = _drop_choices(fd.attrs)
        fd.save(update_fields=["field_type", "attrs"])
        for ff in FlexField.objects.filter(definition=fd):
            ff.attrs = _drop_choices(ff.attrs)
            ff.save(update_fields=["attrs"])


class Scripts:
    requires = []
    operations = [(forward, backward)]
