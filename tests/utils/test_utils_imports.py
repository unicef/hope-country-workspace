from unittest.mock import Mock

import pytest

from country_workspace.utils.imports import validate_alien_fields


def test_validate_alien_fields_no_mapping_no_errors() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "field2": "value2"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "field1"
    field2_mock = Mock()
    field2_mock.name = "field2"
    dc_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = None

    from country_workspace.models import Household

    instance.__class__ = Household

    validate_alien_fields(instance)


def test_validate_alien_fields_with_mapping_no_errors() -> None:
    instance = Mock()
    instance.flex_fields = {"source_field1": "value1", "source_field2": "value2"}

    dc_mock = Mock()
    mapping_importer_mock = Mock()
    mapping_importer_mock.rules_as_dict = {
        "source_field1": "target_field1",
        "source_field2": "target_field2",
    }
    dc_mock.mapping_importers.all.return_value = [mapping_importer_mock]

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "target_field1"
    field2_mock = Mock()
    field2_mock.name = "target_field2"
    dc_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = None

    from country_workspace.models import Household

    instance.__class__ = Household

    validate_alien_fields(instance)


def test_validate_alien_fields_with_prefix() -> None:
    instance = Mock()
    instance.flex_fields = {"pp_field1": "value1"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = "pp_"
    field_mock = Mock()
    field_mock.name = "field1"
    dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = None

    from country_workspace.models import Household

    instance.__class__ = Household

    validate_alien_fields(instance)


def test_validate_alien_fields_raises_error_for_alien_fields() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "alien_field": "value2"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"
    dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = None

    from country_workspace.models import Household

    instance.__class__ = Household

    with pytest.raises(ValueError, match=r"Alien values found for: \{'alien_field'\}"):
        validate_alien_fields(instance)


def test_validate_alien_fields_with_mapping_unmapped_field() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "field2": "value2"}

    dc_mock = Mock()
    mapping_importer_mock = Mock()
    mapping_importer_mock.rules_as_dict = {"field1": "mapped_field1"}
    dc_mock.mapping_importers.all.return_value = [mapping_importer_mock]

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "mapped_field1"
    field2_mock = Mock()
    field2_mock.name = "field2"
    dc_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = None

    from country_workspace.models import Household

    instance.__class__ = Household

    validate_alien_fields(instance)


def test_validate_alien_fields_without_dc() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "field2": "value2"}

    instance.batch.program.household_checker = None
    instance.batch.program.hh_alien_columns_to_ignore = None

    from country_workspace.models import Household

    instance.__class__ = Household

    assert validate_alien_fields(instance) is None


def test_validate_alien_fields_individual() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "field2": "value2"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "field1"
    field2_mock = Mock()
    field2_mock.name = "field2"
    dc_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    instance.batch.program.individual_checker = dc_mock
    instance.batch.program.ind_alien_columns_to_ignore = None

    from country_workspace.models import Individual

    instance.__class__ = Individual

    validate_alien_fields(instance)


def test_validate_alien_fields_with_ignored_columns() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "alien_field": "value2", "another_alien": "value3"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"
    dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = "alien_field\nanother_alien"

    from country_workspace.models import Household

    instance.__class__ = Household

    validate_alien_fields(instance)


def test_validate_alien_fields_with_partial_ignored_columns() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "alien_field": "value2", "not_ignored_alien": "value3"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"
    dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = "alien_field"

    from country_workspace.models import Household

    instance.__class__ = Household

    with pytest.raises(ValueError, match=r"Alien values found for: \{'not_ignored_alien'\}"):
        validate_alien_fields(instance)


def test_validate_alien_fields_ignored_columns_with_whitespace() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "alien_field": "value2"}

    dc_mock = Mock()
    dc_mock.mapping_importers.all.return_value = []

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"
    dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    instance.batch.program.household_checker = dc_mock
    instance.batch.program.hh_alien_columns_to_ignore = "  alien_field  \n\n"

    from country_workspace.models import Household

    instance.__class__ = Household

    validate_alien_fields(instance)
