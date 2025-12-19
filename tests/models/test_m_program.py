import pytest
from unittest.mock import MagicMock, patch
from tests.extras.testutils.factories import (
    ProgramFactory,
    IndividualFactory,
    HouseholdFactory,
    MappingImporterFactory,
    OfficeFactory,
)

from country_workspace.models import (
    Program,
    DataSerializer,
    Individual,
    Household,
    MappingImporter,
)
from tests.extras.testutils.factories.serializer import DataSerializerFactory
from typing import Any


@pytest.fixture
def program():
    return ProgramFactory()


@pytest.fixture
def program_without_serializer():
    return ProgramFactory(serializer=None)


@pytest.fixture
def custom_serializer():
    code = """function replaceEmptyStrings(data) {
    var result = [];
    for (var i = 0; i < data.length; i++) {
        var obj = data[i];
        var newObj = {};
        for (var key in obj) {
            if (obj.hasOwnProperty(key)) {
                newObj[key] = obj[key] === "" ? "IS_EMPTY" : obj[key];
            }
        }
        result.push(newObj);
    }
    return result;
}"""
    return DataSerializerFactory(code=code)


def test_program_serialize(program: Program):
    data = [{"foo": "bar"}]
    result = program.serialize(data)
    assert result == data


def test_program_no_serializer(program: Program):
    program.serializer = None
    data = [{"foo": "bar"}]
    result = program.serialize(data)
    assert result == data


def test_program_serializer_for_individuals(program: Program):
    IndividualFactory.create_batch(3, batch__program=program)
    individuals_data = [ind.apply_grouping() for ind in program.individuals.all()]
    result = program.serialize(individuals_data)

    assert isinstance(result, list)
    assert len(result) == len(individuals_data)

    if result and individuals_data:
        assert set(result[0].keys()) == set(individuals_data[0].keys())


def test_program_serializer_for_households(program: Program):
    HouseholdFactory.create_batch(3, batch__program=program)
    households_data = [hh.apply_grouping() for hh in program.households.all()]
    result = program.serialize(households_data)

    assert isinstance(result, list)
    assert len(result) == len(households_data)

    if result and households_data:
        assert set(result[0].keys()) == set(households_data[0].keys())


def _find_empty_fields(data):
    empty_fields = []
    for item in data:
        for key, value in item.items():
            if value == "":
                empty_fields.append((key, value))
    return empty_fields


def _verify_empty_strings_replaced(result, individuals_data):
    for item in result:
        for key, value in item.items():
            if value == "IS_EMPTY":
                original_item = next((orig for orig in individuals_data if orig.get(key) == ""), None)
                assert original_item is not None, f"Field {key} was not originally empty"


def _verify_non_empty_values_unchanged(result, individuals_data):
    for i, item in enumerate(result):
        original_item = individuals_data[i]
        for key, value in item.items():
            if value != "IS_EMPTY":
                assert value == original_item.get(key), f"Non-empty value for {key} was changed"


def _verify_mutation_occurred(result, empty_fields):
    if empty_fields:
        is_empty_count = sum(1 for item in result for value in item.values() if value == "IS_EMPTY")
        assert is_empty_count > 0, "No empty strings were replaced with IS_EMPTY"


def test_program_serializer_mutation_for_individuals(program: Program, custom_serializer: DataSerializer):
    program.serializer = custom_serializer
    program.save()

    IndividualFactory.create_batch(3, batch__program=program)
    individuals_data = [ind.apply_grouping() for ind in program.individuals.all()]
    empty_fields = _find_empty_fields(individuals_data)

    result = program.serialize(individuals_data)

    assert isinstance(result, list)
    assert len(result) == len(individuals_data)

    _verify_empty_strings_replaced(result, individuals_data)
    _verify_non_empty_values_unchanged(result, individuals_data)
    _verify_mutation_occurred(result, empty_fields)


def test_program_serializer_for_individuals_with_empty_serializer(program_without_serializer: Program):
    IndividualFactory.create_batch(3, batch__program=program_without_serializer)
    individuals_data = list(program_without_serializer.individuals.values())

    result = program_without_serializer.serialize(individuals_data)
    assert result == individuals_data


def test_program_serializer_for_households_with_empty_serializer(program_without_serializer: Program):
    HouseholdFactory.create_batch(3, batch__program=program_without_serializer)
    households_data = list(program_without_serializer.households.values())

    result = program_without_serializer.serialize(households_data)
    assert result == households_data


@pytest.mark.parametrize(
    ("attr_name", "model_cls", "value", "expected"),
    [
        (
            "household_columns",
            Household,
            "name\nid\nflex_fields__consent\n\n",
            ["name", "id", "flex_fields__consent"],
        ),
        (
            "individual_columns",
            Individual,
            "name\nhousehold\nflex_fields__gender",
            ["name", "household", "flex_fields__gender"],
        ),
    ],
)
def test_program_get_columns_for(program: Program, attr_name: str, model_cls: type, value: str, expected: list) -> None:
    setattr(program, attr_name, value)
    assert program.get_columns_for(model_cls) == expected


def test_program_get_columns_for_unsupported_model_raises(program: Program) -> None:
    with pytest.raises(TypeError):
        program.get_columns_for(object)


@pytest.mark.parametrize(
    ("model_cls", "expected"),
    [
        (Household, {"h": 1}),
        (Individual, {"i": 2}),
    ],
)
def test_program_get_default_fields_for_scope(program: Program, model_cls: type, expected: dict) -> None:
    program.system_fields = {
        "default_fields": {
            "household": {"h": 1},
            "individual": {"i": 2},
        }
    }
    assert program.get_default_fields_for(model_cls) == expected


@pytest.mark.parametrize(
    ("model_cls", "scope_key"),
    [
        (Household, "household"),
        (Individual, "individual"),
    ],
)
def test_program_save_default_fields_for_updates_scope(program: Program, model_cls: type, scope_key: str) -> None:
    program.system_fields = {"default_fields": {"other": {"keep": True}}}

    defaults = {"foo": "bar"}
    program.save_default_fields_for(model_cls, defaults)

    assert program.system_fields["default_fields"][scope_key] == defaults
    assert program.system_fields["default_fields"]["other"] == {"keep": True}


def test_program_apply_default_fields_without_defaults_returns_original(program: Program) -> None:
    program.system_fields = {}
    data = {"field": "value"}

    result = program.apply_default_fields(Household, data)

    assert result is data
    assert result == {"field": "value"}


def test_program_apply_default_fields_applies_only_missing_or_none(program: Program) -> None:
    program.system_fields = {
        "default_fields": {
            "household": {"a": 1, "b": 2},
        }
    }
    data = {"a": "keep", "b": None, "c": 3}

    result = program.apply_default_fields(Household, data)

    assert result is data
    assert result == {"a": "keep", "b": 2, "c": 3}


def test_apply_mapping_importer_with_mapping_id(program: Program):
    mapping_id = 123
    data: dict[str, Any] = {"name": "Test"}
    mock_importer = MagicMock(spec=MappingImporter)

    with patch("country_workspace.models.MappingImporter.objects.filter") as mock_filter:
        mock_filter.return_value.first.return_value = mock_importer
        result = program.apply_mapping_importer(Household, data, mapping_id=mapping_id)

        mock_filter.assert_called_once_with(id=mapping_id)
        mock_importer.apply.assert_called_once_with(data)
        assert result == data


def test_apply_mapping_importer_with_invalid_mapping_id(program: Program):
    mapping_id = 999
    data: dict[str, Any] = {"name": "Test"}

    with patch("country_workspace.models.MappingImporter.objects.filter") as mock_filter:
        mock_filter.return_value.first.return_value = None
        result = program.apply_mapping_importer(Household, data, mapping_id=mapping_id)

        mock_filter.assert_called_once_with(id=mapping_id)
        assert result == data


def test_apply_mapping_importer_from_checker(program: Program):
    data: dict[str, Any] = {"name": "Test"}

    office = program.country_office
    other_office = OfficeFactory()

    # Importer for the correct office - should be used
    importer1 = MappingImporterFactory(office=office)
    importer1.apply = MagicMock()

    # Second importer for the correct office - should be used
    importer2 = MappingImporterFactory(office=office)
    importer2.apply = MagicMock()

    # Importer for another office - should NOT be used
    importer3 = MappingImporterFactory(office=other_office)
    importer3.apply = MagicMock()

    mock_checker = MagicMock()
    mock_checker.mapping_importers.filter.return_value = [importer1, importer2]

    with patch.object(program, "get_checker_for", return_value=mock_checker) as mock_get_checker_for:
        result = program.apply_mapping_importer(Household, data)

        mock_get_checker_for.assert_called_once_with(Household)
        mock_checker.mapping_importers.filter.assert_called_once_with(office=office)
        importer1.apply.assert_called_once_with(data)
        importer2.apply.assert_called_once_with(data)
        importer3.apply.assert_not_called()
        assert result == data


def test_apply_mapping_importer_returns_early_when_checker_is_none(program: Program) -> None:
    data: dict[str, Any] = {"name": "Test"}

    with (
        patch.object(program, "get_checker_for", return_value=None) as mock_get_checker_for,
        patch("country_workspace.models.MappingImporter.objects.filter") as mock_filter,
    ):
        result = program.apply_mapping_importer(Household, data)

    mock_get_checker_for.assert_called_once_with(Household)
    mock_filter.assert_not_called()
    assert result is data
    assert result == data
