from contextlib import suppress
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django import forms
from django.utils.text import slugify
from packaging.version import Version

from hope_flex_fields.models import FieldDefinition, Fieldset
from country_workspace.contrib.hope.constants import PEOPLE_FIELDSET_NAME
from country_workspace.contrib.hope.geo import CountryChoice
from country_workspace.utils.flex_fields import ConsentSharingChoice

from concurrency.utils import fqn
from hope_flex_fields.registry import field_registry
from country_workspace.models import SyncLog


field_registry.register(ConsentSharingChoice)
field_registry.register(CountryChoice)


_script_for_version = Version("0.1.0")


FIELDS = {
    "observed_disability": {"name": "HOPE IND ObservedDisability", "defaults": {"field_type": fqn(forms.ChoiceField)}},
    "marital_status": {"name": "HOPE IND MaritalStatus", "defaults": {"field_type": fqn(forms.ChoiceField)}},
    "country_origin": {"name": "CountryOrigin", "defaults": {"field_type": fqn(CountryChoice)}},
    "village": {"name": "Village", "defaults": {"field_type": fqn(forms.CharField)}},
    "phone_no": {"name": "PhoneNo", "defaults": {"field_type": fqn(forms.CharField)}},
    "phone_no_alternative": {"name": "PhoneNoAlternative", "defaults": {"field_type": fqn(forms.CharField)}},
    "consent_sharing": {"name": "HOPE HH Consent Sharing", "defaults": {"field_type": fqn(ConsentSharingChoice)}},
}


def forward() -> None:
    with transaction.atomic():
        fs, __ = Fieldset.objects.get_or_create(name=PEOPLE_FIELDSET_NAME)
        for field_name, field_def in FIELDS.items():
            field_def["defaults"]["slug"] = slugify(field_def["name"])
            fd, __ = FieldDefinition.objects.get_or_create(**field_def)
            fs.fields.update_or_create(
                name=field_name,
                defaults={
                    "definition": fd,
                },
            )
        SyncLog.objects.create_lookups()


def backward() -> None:
    with transaction.atomic():
        try:
            fs = Fieldset.objects.get(name=PEOPLE_FIELDSET_NAME)
        except Fieldset.DoesNotExist:
            return

        ct = ContentType.objects.get_for_model(FieldDefinition)

        for field_name, field_def in FIELDS.items():
            fs.fields.filter(name=field_name).delete()
            with suppress(FieldDefinition.DoesNotExist):
                fd = FieldDefinition.objects.get(name=field_def["name"])
                if not fd.instances.exists():
                    SyncLog.objects.filter(content_type=ct, object_id=fd.pk).delete()
                    fd.delete()


class Scripts:
    requires = []
    operations = [(forward, backward)]
