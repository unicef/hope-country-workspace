from unittest.mock import Mock

import pytest

from country_workspace.utils.imports import validate_alien_fields, get_originating_id, normalize_file_name


def test_validate_alien_fields_no_mapping_no_errors() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "field2": "value2"}
    instance.members.all.return_value = []

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


def test_validate_alien_fields_with_invalid_instance_type() -> None:
    instance = Mock()

    assert validate_alien_fields(instance) is None


def test_validate_alien_fields_skips_when_program_check_disabled() -> None:
    instance = Mock()
    instance.program.alien_validation_enabled = False

    from country_workspace.models import Household

    instance.__class__ = Household

    assert validate_alien_fields(instance) is None


def test_validate_alien_fields_with_mapping_no_errors() -> None:
    instance = Mock()
    instance.flex_fields = {"target_field1": "value1", "target_field2": "value2"}
    instance.members.all.return_value = []

    dc_mock = Mock()

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
    instance.members.all.return_value = []

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
    instance.members.all.return_value = []

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

    with pytest.raises(ValueError, match=r"Alien values found - Household: alien_field"):
        validate_alien_fields(instance)


def test_validate_alien_fields_with_mapping_unmapped_field() -> None:
    instance = Mock()
    instance.flex_fields = {"mapped_field1": "value1", "field2": "value2"}
    instance.members.all.return_value = []

    dc_mock = Mock()

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
    instance.members.all.return_value = []

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
    instance.members.all.return_value = []

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
    instance.members.all.return_value = []

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

    with pytest.raises(ValueError, match=r"Alien values found - Household: not_ignored_alien"):
        validate_alien_fields(instance)


def test_validate_alien_fields_ignored_columns_with_whitespace() -> None:
    instance = Mock()
    instance.flex_fields = {"field1": "value1", "alien_field": "value2"}
    instance.members.all.return_value = []

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


def test_validate_alien_fields_household_with_member_aliens() -> None:
    from country_workspace.models import Household, Individual

    hh_instance = Mock()
    hh_instance.flex_fields = {"field1": "value1"}
    hh_instance.__class__ = Household

    member = Mock()
    member.flex_fields = {"field1": "value1", "alien_field": "value2"}
    member.__class__ = Individual

    hh_instance.members.all.return_value = [member]

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"

    hh_dc_mock = Mock()
    hh_dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    ind_dc_mock = Mock()
    ind_dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    hh_instance.batch.program.household_checker = hh_dc_mock
    hh_instance.batch.program.hh_alien_columns_to_ignore = None
    member.batch.program.individual_checker = ind_dc_mock
    member.batch.program.ind_alien_columns_to_ignore = None

    with pytest.raises(ValueError, match=r"Alien values found - Individual: alien_field"):
        validate_alien_fields(hh_instance)


def test_validate_alien_fields_household_and_member_both_have_aliens() -> None:
    from country_workspace.models import Household, Individual

    hh_instance = Mock()
    hh_instance.flex_fields = {"field1": "value1", "hh_alien": "value2"}
    hh_instance.__class__ = Household

    member = Mock()
    member.flex_fields = {"field1": "value1", "ind_alien": "value2"}
    member.__class__ = Individual

    hh_instance.members.all.return_value = [member]

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"

    hh_dc_mock = Mock()
    hh_dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    ind_dc_mock = Mock()
    ind_dc_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    hh_instance.batch.program.household_checker = hh_dc_mock
    hh_instance.batch.program.hh_alien_columns_to_ignore = None
    member.batch.program.individual_checker = ind_dc_mock
    member.batch.program.ind_alien_columns_to_ignore = None

    with pytest.raises(ValueError, match=r"Alien values found - Household: hh_alien; Individual: ind_alien"):
        validate_alien_fields(hh_instance)


def test_get_originating_id() -> None:
    args = ["arg1", "arg2", "arg3"]
    expected_output = "arg1#arg2#arg3"
    output = get_originating_id(*args)
    assert output == expected_output


def test_normalize_file_name() -> None:
    file_name = "rdi (a).xlsx"
    expected_output = "rdi-a.xlsx"
    output = normalize_file_name(file_name)
    assert output == expected_output
