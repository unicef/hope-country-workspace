import factory
from country_workspace.mapping.models import MappingProfile, FieldMappingRule
from .base import AutoRegisterModelFactory
from .user import UserFactory


class MappingProfileFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda n: f"Mapping Profile {n}")
    description = factory.Faker("sentence", nb_words=4)
    source_type = MappingProfile.SourceType.ANY
    import_schema = MappingProfile.ImportSchema.ANY
    created_by = factory.SubFactory(UserFactory)
    is_active = True
    parent = None

    class Meta:
        model = MappingProfile
        django_get_or_create = ("name",)

    @factory.post_generation
    def programs(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            if isinstance(extracted, (list, tuple)):
                self.program.set(extracted)
            else:
                self.program.add(extracted)


class FieldMappingRuleFactory(AutoRegisterModelFactory):
    profile = factory.SubFactory(MappingProfileFactory)
    name = factory.Sequence(lambda n: f"Rule {n}")
    expression = "{'mapped_field': 'value'}"
    description = factory.Faker("sentence", nb_words=6)
    order = factory.Sequence(lambda n: n * 10)
    created_by = factory.SubFactory(UserFactory)
    is_active = True

    class Meta:
        model = FieldMappingRule
        django_get_or_create = ("name", "profile")
