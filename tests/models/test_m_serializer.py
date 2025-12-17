import pytest
from django.core.exceptions import ValidationError

from country_workspace.models import DataSerializer
from testutils.factories.serializer import DataSerializerFactory


@pytest.fixture
def data_serializer():
    return DataSerializerFactory()


def test_serialize(data_serializer: DataSerializer):
    data = [{"foo": "bar"}]
    result = data_serializer.serialize(data)
    assert result == data


def test_str(data_serializer: DataSerializer):
    assert str(data_serializer) == f"DataSerializer: {data_serializer.name}"


def test_clean_valid(data_serializer: DataSerializer):
    data_serializer.clean()


@pytest.mark.parametrize("code", ["", "function {"])
def test_clean_invalid_js(data_serializer: DataSerializer, code: str):
    data_serializer.code = code
    with pytest.raises(ValidationError, match=r"Invalid JavaScript code"):
        data_serializer.clean()
