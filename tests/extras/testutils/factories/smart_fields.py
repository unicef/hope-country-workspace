from django import forms

import factory.fuzzy
from hope_flex_fields.models import DataChecker, DataCheckerFieldset, FieldDefinition, Fieldset, FlexField
from testutils.factories import AutoRegisterModelFactory


class FieldDefinitionFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda d: "FieldDefinition-%s" % d)
    field_type = factory.fuzzy.FuzzyChoice(
        [forms.CharField, forms.IntegerField, forms.FloatField, forms.ChoiceField, forms.BooleanField]
    )
    attrs = {}

    class Meta:
        model = FieldDefinition
        django_get_or_create = ("name",)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        if "attrs" in kwargs:
            from hope_flex_fields.utils import get_kwargs_from_field_class

            attrs = get_kwargs_from_field_class(kwargs["field_type"])
            attrs.update(**kwargs["attrs"])
            kwargs["attrs"] = attrs
        return super()._create(model_class, *args, **kwargs)


class FieldsetFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda d: "Fieldset-%s" % d)
    extends = None

    class Meta:
        model = Fieldset
        django_get_or_create = ("name",)


class FlexFieldFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda d: "FieldsetField-%s" % d)
    fieldset = factory.SubFactory(FieldsetFactory)
    field = factory.SubFactory(FieldDefinitionFactory)
    attrs = {}

    class Meta:
        model = FlexField
        django_get_or_create = ("name", "fieldset")


class DataCheckerFactory(AutoRegisterModelFactory):
    name = factory.Sequence(lambda d: "DataChecker-%s" % d)

    class Meta:
        model = DataChecker
        django_get_or_create = ("name",)

    @factory.post_generation
    def fields(self, create, extracted, **kwargs):
        if extracted:
            fs = FieldsetFactory()
            for i in extracted:
                FlexFieldFactory(fieldset=fs, name=i)
            self.fieldsets.add(fs)


class DataCheckerFieldsetFactory(AutoRegisterModelFactory):
    checker = factory.SubFactory(DataCheckerFactory)
    fieldset = factory.SubFactory(FieldsetFactory)
    prefix = "aaa"

    class Meta:
        model = DataCheckerFieldset
        django_get_or_create = ("checker", "prefix")
