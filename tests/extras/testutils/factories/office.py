import factory

from country_workspace.models import Office

from .base import AutoRegisterModelFactory


class OfficeFactory(AutoRegisterModelFactory):
    _COUNTRIES = [
        "Afghanistan",
        "Ukraine",
        "Niger",
        "South Sudan",
        "Somalia",
        "Belarus",
    ]
    hope_id = factory.Sequence(lambda n: f"office-{n}")
    name = factory.Iterator(_COUNTRIES)
    code = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))
    slug = factory.LazyAttribute(lambda o: o.name.lower().replace(" ", "_"))
    active = True

    class Meta:
        model = Office
        django_get_or_create = ("name",)
