from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from pytest_mock import MockerFixture

from country_workspace.models import DataSerializer, Household, Individual, MappingImporter, Program
from tests.extras.testutils.factories import (
    HouseholdFactory,
    IndividualFactory,
    MappingImporterFactory,
    OfficeFactory,
    ProgramFactory,
)
from tests.extras.testutils.factories.serializer import DataSerializerFactory


pytestmark = pytest.mark.django_db


@pytest.fixture
def program() -> Program:
    return ProgramFactory()


@pytest.fixture
def program_without_serializer() -> Program:
    return ProgramFactory(serializer=None)


@pytest.fixture
def custom_serializer() -> DataSerializer:
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


def test_program_serialize(program: Program) -> None:
    data = [{"foo": "bar"}]

    assert program.serialize(data) == data


def test_program_no_serializer(program: Program) -> None:
    program.serializer = None
    data = [{"foo": "bar"}]

    assert program.serialize(data) == data


def test_program_serializer_for_individuals(program: Program) -> None:
    IndividualFactory.create_batch(3, batch__program=program)
    individuals_data = [ind.apply_grouping() for ind in program.individuals.all()]

    result = program.serialize(individuals_data)

    assert isinstance(result, list)
    assert len(result) == len(individuals_data)

    if result and individuals_data:
        assert set(result[0].keys()) == set(individuals_data[0].keys())


def test_program_serializer_for_households(program: Program) -> None:
    HouseholdFactory.create_batch(3, batch__program=program)
    households_data = [hh.apply_grouping() for hh in program.households.all()]

    result = program.serialize(households_data)

    assert isinstance(result, list)
    assert len(result) == len(households_data)

    if result and households_data:
        assert set(result[0].keys()) == set(households_data[0].keys())


def _find_empty_fields(data: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    return [(key, value) for item in data for key, value in item.items() if value == ""]


def _verify_empty_strings_replaced(result: list[dict[str, Any]], source: list[dict[str, Any]]) -> None:
    for item in result:
        for key, value in item.items():
            if value == "IS_EMPTY":
                assert next((original for original in source if original.get(key) == ""), None) is not None


def _verify_non_empty_values_unchanged(result: list[dict[str, Any]], source: list[dict[str, Any]]) -> None:
    for item, original_item in zip(result, source, strict=True):
        for key, value in item.items():
            if value != "IS_EMPTY":
                assert value == original_item.get(key)


def _verify_mutation_occurred(result: list[dict[str, Any]], empty_fields: list[tuple[str, Any]]) -> None:
    if empty_fields:
        assert any(value == "IS_EMPTY" for item in result for value in item.values())


def test_program_serializer_mutation_for_individuals(program: Program, custom_serializer: DataSerializer) -> None:
    program.serializer = custom_serializer
    program.save(update_fields=["serializer"])

    IndividualFactory.create_batch(3, batch__program=program)
    individuals_data = [ind.apply_grouping() for ind in program.individuals.all()]
    empty_fields = _find_empty_fields(individuals_data)

    result = program.serialize(individuals_data)

    assert isinstance(result, list)
    assert len(result) == len(individuals_data)

    _verify_empty_strings_replaced(result, individuals_data)
    _verify_non_empty_values_unchanged(result, individuals_data)
    _verify_mutation_occurred(result, empty_fields)


def test_program_serializer_for_individuals_with_empty_serializer(program_without_serializer: Program) -> None:
    IndividualFactory.create_batch(3, batch__program=program_without_serializer)
    individuals_data = list(program_without_serializer.individuals.values())

    assert program_without_serializer.serialize(individuals_data) == individuals_data


def test_program_serializer_for_households_with_empty_serializer(program_without_serializer: Program) -> None:
    HouseholdFactory.create_batch(3, batch__program=program_without_serializer)
    households_data = list(program_without_serializer.households.values())

    assert program_without_serializer.serialize(households_data) == households_data


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
def test_program_get_columns_for(
    program: Program,
    attr_name: str,
    model_cls: type,
    value: str,
    expected: list[str],
) -> None:
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
def test_program_get_default_fields_for_scope(program: Program, model_cls: type, expected: dict[str, int]) -> None:
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


@pytest.mark.parametrize(
    ("model_cls", "field_name"),
    [
        (Household, "household_id"),
        (Individual, "national_id"),
    ],
)
def test_program_unique_field_for_scope(program: Program, model_cls: type, field_name: str) -> None:
    program.system_fields = {
        "unique_fields": {
            "household": "household_id",
            "individual": "national_id",
        }
    }
    assert program.get_unique_field_for(model_cls) == field_name


@pytest.mark.parametrize(
    ("model_cls", "scope_key"),
    [
        (Household, "household"),
        (Individual, "individual"),
    ],
)
def test_program_save_unique_field_for_updates_scope(program: Program, model_cls: type, scope_key: str) -> None:
    program.system_fields = {"removed_unique_values": {"other": {"keep": ["x"]}}}

    program.save_unique_field_for(model_cls, "field_1")

    assert program.system_fields["unique_fields"][scope_key] == "field_1"
    assert program.system_fields["removed_unique_values"][scope_key]["field_1"] == []
    assert program.system_fields["removed_unique_values"]["other"] == {"keep": ["x"]}


def test_program_add_removed_unique_values_for(program: Program) -> None:
    program.system_fields = {
        "unique_fields": {"individual": "national_id"},
        "removed_unique_values": {"individual": {"national_id": ["A"]}},
    }

    program.add_removed_unique_values_for(Individual, ["A", "B", " ", None, 123])

    assert set(program.get_removed_unique_values_for(Individual)) == {"A", "B", "123"}


def test_program_has_any_data(program: Program) -> None:
    from tests.extras.testutils.factories import BatchFactory

    assert not program.has_any_data()
    batch = BatchFactory(program=program, country_office=program.country_office)
    IndividualFactory(batch=batch)
    assert program.has_any_data()


def test_program_has_any_data_unsaved_program() -> None:
    unsaved_program = ProgramFactory.build()
    assert unsaved_program.has_any_data() is False


def test_program_has_any_data_proxy_instance() -> None:
    from tests.extras.testutils.factories import CountryProgramFactory, BatchFactory

    program = CountryProgramFactory()
    assert program.has_any_data() is False

    BatchFactory(program=program, country_office=program.country_office)
    assert program.has_any_data() is True


def test_program_save_unique_field_for_none_removes_scope(program: Program) -> None:
    program.system_fields = {
        "unique_fields": {"individual": "national_id", "household": "household_id"},
        "removed_unique_values": {"individual": {"national_id": ["A"]}},
    }

    program.save_unique_field_for(Individual, None)

    assert "individual" not in program.system_fields["unique_fields"]
    assert program.system_fields["unique_fields"]["household"] == "household_id"


def test_program_get_removed_unique_values_for_without_unique_field(program: Program) -> None:
    program.system_fields = {"removed_unique_values": {"individual": {"national_id": ["A"]}}}
    assert program.get_removed_unique_values_for(Individual) == []


def test_program_add_removed_unique_values_for_without_unique_field(program: Program) -> None:
    program.system_fields = {}
    program.add_removed_unique_values_for(Individual, ["A"])
    assert program.system_fields == {}


def test_program_add_removed_unique_values_for_skips_empty_values(program: Program) -> None:
    program.system_fields = {
        "unique_fields": {"individual": "national_id"},
        "removed_unique_values": {"individual": {"national_id": ["A"]}},
    }

    program.add_removed_unique_values_for(Individual, [None, "", "  "])

    assert program.system_fields["removed_unique_values"]["individual"]["national_id"] == ["A"]


def test_program_get_removed_unique_values_for_handles_non_list(program: Program) -> None:
    program.system_fields = {
        "unique_fields": {"individual": "national_id"},
        "removed_unique_values": {"individual": {"national_id": "not-a-list"}},
    }

    assert program.get_removed_unique_values_for(Individual) == []


def test_program_scope_for_unsupported_model_raises(program: Program) -> None:
    with pytest.raises(TypeError):
        program._scope_for(Program)


def test_apply_mapping_importer_with_mapping_id(program: Program, mocker: MockerFixture) -> None:
    mapping_id = 123
    data: dict[str, Any] = {"name": "Test"}
    importer = mocker.MagicMock(spec=MappingImporter)
    importer.apply.return_value = data

    mapping_filter = mocker.patch("country_workspace.models.MappingImporter.objects.filter")
    mapping_filter.return_value.first.return_value = importer

    result = program.apply_mapping_importer(Household, data, mapping_id=mapping_id)

    mapping_filter.assert_called_once_with(id=mapping_id)
    importer.apply.assert_called_once_with(data)
    assert result == data


def test_apply_mapping_importer_with_invalid_mapping_id(program: Program, mocker: MockerFixture) -> None:
    mapping_id = 999
    data: dict[str, Any] = {"name": "Test"}

    mapping_filter = mocker.patch("country_workspace.models.MappingImporter.objects.filter")
    mapping_filter.return_value.first.return_value = None

    result = program.apply_mapping_importer(Household, data, mapping_id=mapping_id)

    mapping_filter.assert_called_once_with(id=mapping_id)
    assert result == data


def test_apply_mapping_importer_from_checker(program: Program, mocker: MockerFixture) -> None:
    data: dict[str, Any] = {"name": "Test"}
    office = program.country_office
    other_office = OfficeFactory()

    importer1 = MappingImporterFactory(office=office)
    importer1.apply = mocker.MagicMock(return_value=data)

    importer2 = MappingImporterFactory(office=office)
    importer2.apply = mocker.MagicMock(return_value=data)

    importer3 = MappingImporterFactory(office=other_office)
    importer3.apply = mocker.MagicMock()

    checker = mocker.MagicMock()
    checker.mapping_importers.filter.return_value = [importer1, importer2]

    get_checker = mocker.patch.object(program, "get_checker_for", return_value=checker)

    result = program.apply_mapping_importer(Household, data)

    get_checker.assert_called_once_with(Household)
    checker.mapping_importers.filter.assert_called_once_with(office=office)
    importer1.apply.assert_called_once_with(data)
    importer2.apply.assert_called_once_with(data)
    importer3.apply.assert_not_called()
    assert result == data


def test_apply_mapping_importer_returns_early_when_checker_is_none(program: Program, mocker: MockerFixture) -> None:
    data: dict[str, Any] = {"name": "Test"}

    get_checker = mocker.patch.object(program, "get_checker_for", return_value=None)
    mapping_filter = mocker.patch("country_workspace.models.MappingImporter.objects.filter")

    result = program.apply_mapping_importer(Household, data)

    get_checker.assert_called_once_with(Household)
    mapping_filter.assert_not_called()
    assert result == data


def test_apply_mapping_importer_mapping_id_only(program: Program, mocker: MockerFixture) -> None:
    mapping_id = 123
    data: dict[str, Any] = {"gender": "M"}
    importer = mocker.MagicMock(spec=MappingImporter)
    importer.apply.return_value = {"sex": "M"}

    mapping_filter = mocker.patch("country_workspace.models.MappingImporter.objects.filter")
    mapping_filter.return_value.first.return_value = importer

    result = program.apply_mapping_importer(Household, data, mapping_id=mapping_id)

    mapping_filter.assert_called_once_with(id=mapping_id)
    importer.apply.assert_called_once_with(data)
    assert result == {"sex": "M"}


def test_apply_mapping_importer_checker_with_no_mappings(program: Program, mocker: MockerFixture) -> None:
    data: dict[str, Any] = {"gender": "M"}
    checker = mocker.MagicMock()
    checker.mapping_importers.filter.return_value = []

    mocker.patch.object(program, "get_checker_for", return_value=checker)

    result = program.apply_mapping_importer(Household, data)

    checker.mapping_importers.filter.assert_called_once_with(office=program.country_office)
    assert result == data


@pytest.mark.parametrize(
    ("code", "slug", "expected"),
    [
        (None, "co", None),
        ("P", None, None),
        ("P", "co", "co-p"),
    ],
)
def test_program_unicef_id(program: Program, code: str | None, slug: str | None, expected: str | None) -> None:
    program.code = code
    program.country_office.slug = slug

    if expected is None:
        with pytest.raises(ImproperlyConfigured):
            _ = program.unicef_id
    else:
        assert program.unicef_id == expected
