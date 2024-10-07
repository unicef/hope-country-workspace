import factory

from country_workspace.workspaces.models import CountryChecker
from testutils.factories import CountryOfficeFactory, AutoRegisterModelFactory


class CountryCheckerFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda d: "DataChecker-%s" % d)

    country_office = factory.SubFactory(CountryOfficeFactory)
    class Meta:
        model = CountryChecker


# class DataCheckerFieldsetFactory(AutoRegisterModelFactory):
#     checker = factory.SubFactory(DataCheckerFactory)
#     fieldset = factory.SubFactory(FieldsetFactory)
#     prefix = "aaa"
#
#     class Meta:
#         model = DataCheckerFieldset
#         django_get_or_create = ("checker", "prefix")

# class FlexFieldFactory(AutoRegisterModelFactory):
#     name = factory.Sequence(lambda d: "FieldsetField-%s" % d)
#     fieldset = factory.SubFactory(FieldsetFactory)
#     field = factory.SubFactory(FieldDefinitionFactory)
#     attrs = {}
#
#     class Meta:
#         model = FlexField
#         django_get_or_create = ("name", "fieldset")

# class FieldsetFactory(AutoRegisterModelFactory):
#     name = factory.Sequence(lambda d: "Fieldset-%s" % d)
#     extends = None
#
#     class Meta:
#         model = Fieldset
#         django_get_or_create = ("name",)

# class FieldsetFactory(AutoRegisterModelFactory):
#     name = factory.Sequence(lambda d: "Fieldset-%s" % d)
#     extends = None
#
#     class Meta:
#         model = Fieldset
#         django_get_or_create = ("name",)
