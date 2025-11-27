from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from country_workspace.utils.imports import validate_alien_fields


def test_validate_alien_fields_no_mapping_no_errors(mocker: MockerFixture) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.utils.imports.clean_field_names")
    clean_field_names_mock.return_value = {"field1": "value1", "field2": "value2"}

    sheet_mock = iter([{"raw_field1": "value1", "raw_field2": "value2"}])

    datachecker_mock = Mock()
    datachecker_mock.mappingimporter = None

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "field1"
    field2_mock = Mock()
    field2_mock.name = "field2"
    datachecker_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    validate_alien_fields(sheet_mock, datachecker_mock)

    clean_field_names_mock.assert_called_once_with({"raw_field1": "value1", "raw_field2": "value2"})


def test_validate_alien_fields_with_mapping_no_errors(mocker: MockerFixture) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.utils.imports.clean_field_names")
    clean_field_names_mock.return_value = {"source_field1": "value1", "source_field2": "value2"}

    sheet_mock = iter([{"raw_field": "value"}])

    datachecker_mock = Mock()
    mapping_importer_mock = Mock()
    mapping_importer_mock.rules_as_dict = {
        "source_field1": "target_field1",
        "source_field2": "target_field2",
    }
    datachecker_mock.mappingimporter = mapping_importer_mock

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "target_field1"
    field2_mock = Mock()
    field2_mock.name = "target_field2"
    datachecker_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    validate_alien_fields(sheet_mock, datachecker_mock)


def test_validate_alien_fields_with_prefix(mocker: MockerFixture) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.utils.imports.clean_field_names")
    clean_field_names_mock.return_value = {"pp_field1": "value1"}

    sheet_mock = iter([{"raw_field": "value"}])

    datachecker_mock = Mock()
    datachecker_mock.mappingimporter = None

    fieldset_mock = Mock()
    fieldset_mock.prefix = "pp_"
    field_mock = Mock()
    field_mock.name = "field1"
    datachecker_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    validate_alien_fields(sheet_mock, datachecker_mock)


def test_validate_alien_fields_raises_error_for_alien_fields(mocker: MockerFixture) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.utils.imports.clean_field_names")
    clean_field_names_mock.return_value = {"field1": "value1", "alien_field": "value2"}

    sheet_mock = iter([{"raw_field": "value"}])

    datachecker_mock = Mock()
    datachecker_mock.mappingimporter = None

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field_mock = Mock()
    field_mock.name = "field1"
    datachecker_mock.get_fields.return_value = [(fieldset_mock, field_mock)]

    with pytest.raises(ValueError, match=r"Alien values found for: \{'alien_field'\}"):
        validate_alien_fields(sheet_mock, datachecker_mock)


def test_validate_alien_fields_with_mapping_unmapped_field(mocker: MockerFixture) -> None:
    clean_field_names_mock = mocker.patch("country_workspace.utils.imports.clean_field_names")
    clean_field_names_mock.return_value = {"field1": "value1", "field2": "value2"}

    sheet_mock = iter([{"raw_field": "value"}])

    datachecker_mock = Mock()
    mapping_importer_mock = Mock()
    mapping_importer_mock.rules_as_dict = {"field1": "mapped_field1"}
    datachecker_mock.mappingimporter = mapping_importer_mock

    fieldset_mock = Mock()
    fieldset_mock.prefix = ""
    field1_mock = Mock()
    field1_mock.name = "mapped_field1"
    field2_mock = Mock()
    field2_mock.name = "field2"
    datachecker_mock.get_fields.return_value = [(fieldset_mock, field1_mock), (fieldset_mock, field2_mock)]

    validate_alien_fields(sheet_mock, datachecker_mock)


def test_validate_alien_fields_without_dc() -> None:
    datachecker = None
    sheet_mock = iter([{"raw_field1": "value1", "raw_field2": "value2"}])

    assert validate_alien_fields(sheet_mock, datachecker) is None
