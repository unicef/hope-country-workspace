from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from country_workspace.utils.imports import generate_validation_job, validate_alien_fields


@pytest.mark.django_db
def test_generate_validation_job(mocker: MockerFixture) -> None:
    fqn_mock = mocker.patch("country_workspace.utils.imports.fqn")
    async_job_class_mock = mocker.patch("country_workspace.utils.imports.AsyncJob")

    queryset_mock = Mock()
    queryset_mock.model._meta.label = "test_app.TestModel"
    values_list_mock = Mock()
    values_list_mock.__iter__ = Mock(return_value=iter([1, 2, 3]))
    queryset_mock.values_list.return_value = values_list_mock

    program_mock = Mock()
    owner_mock = Mock()
    description = "Test validation job"

    result = generate_validation_job(
        description=description,
        owner=owner_mock,
        program=program_mock,
        queryset=queryset_mock,
    )

    queryset_mock.values_list.assert_called_once_with("pk", flat=True)
    async_job_class_mock.objects.create.assert_called_once_with(
        description=description,
        type=async_job_class_mock.JobType.ACTION,
        owner=owner_mock,
        action=fqn_mock.return_value,
        program=program_mock,
        config={"pks": [1, 2, 3], "model_name": "test_app.TestModel"},
    )
    assert result == async_job_class_mock.objects.create.return_value


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
