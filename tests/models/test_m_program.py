import pytest

from country_workspace.models import Program
from testutils.factories import ProgramFactory, IndividualFactory, HouseholdFactory

from country_workspace.models import DataSerializer, Individual, Household
from tests.extras.testutils.factories.serializer import DataSerializerFactory


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
        program.get_columns_for(Program)
