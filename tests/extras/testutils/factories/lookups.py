import factory

from country_workspace.models import Relationship

from .base import AutoRegisterModelFactory


class RelationshipFactory(AutoRegisterModelFactory):
    code = factory.Iterator(
        [
            "HEAD",
            "WIFE_HUSBAND",
            "SON_DAUGHTER",
            "BROTHER_SISTER",
        ]
    )
    label = factory.LazyAttribute(lambda o: o.code.replace("_", " ").capitalize())

    class Meta:
        model = Relationship
        django_get_or_create = ["code"]
