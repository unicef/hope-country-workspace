import pytest

from country_workspace.models import Program
from testutils.factories import ProgramFactory


@pytest.fixture
def program():
    return ProgramFactory()


def test_program_serialize(program: Program):
    data = [{"foo": "bar"}]
    result = program.serialize(data)
    assert result == data


def test_program_no_serializer(program: Program):
    program.serializer = None
    data = [{"foo": "bar"}]
    result = program.serialize(data)
    assert result == data
