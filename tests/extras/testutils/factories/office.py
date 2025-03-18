from operator import itemgetter

import factory

from country_workspace.models import Office

from .base import AutoRegisterModelFactory


class OfficeFactory(AutoRegisterModelFactory):
    _COUNTRIES = [
        ("Afghanistan", "AFG"),
        ("Ukraine", "UKR"),
        ("Niger", "NER"),
        ("South Sudan", "SSD"),
        ("Somalia", "SOM"),
        ("Belarus", "BLR"),
    ]
    hope_id = factory.Sequence(lambda n: f"office-{n}")
    name = factory.Iterator(map(itemgetter(0), _COUNTRIES))
    code = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))
    slug = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))
    active = True
    country_iso_code = factory.Iterator(map(itemgetter(1), _COUNTRIES))

    class Meta:
        model = Office
        django_get_or_create = ("name",)
