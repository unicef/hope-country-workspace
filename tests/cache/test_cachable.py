from unittest.mock import patch, MagicMock

import pytest

from country_workspace.models.base import Cachable


class CachableModelExample(Cachable):
    def __init__(self, pk, country_office, program):
        self.pk = pk
        self._country_office = country_office
        self._program = program

    @property
    def country_office(self):
        return self._country_office

    @property
    def program(self):
        return self._program


@pytest.fixture
def mock_country_office():
    office = MagicMock()
    office.slug = "test-office"
    return office


@pytest.fixture
def mock_program():
    program = MagicMock()
    program.pk = 123
    return program


@pytest.fixture
def cachable_instance(mock_country_office, mock_program):
    return CachableModelExample(pk=456, country_office=mock_country_office, program=mock_program)


def test_get_object_key_no_suffix(cachable_instance):
    with patch("country_workspace.cache.manager.cache_manager.get_cache_version") as mock_version:
        mock_version.return_value = "789"
        key = cachable_instance.get_object_key()

        expected_parts = ["CachableModelExample", "789", "test-office", "123", "456", ""]
        assert key == ":".join(expected_parts)

        mock_version.assert_called_once_with(program=cachable_instance.program)


def test_get_object_key_with_suffix(cachable_instance):
    with patch("country_workspace.cache.manager.cache_manager.get_cache_version") as mock_version:
        mock_version.return_value = "789"
        key = cachable_instance.get_object_key("test-suffix")

        expected_parts = ["CachableModelExample", "789", "test-office", "123", "456", "test-suffix"]
        assert key == ":".join(expected_parts)

        mock_version.assert_called_once_with(program=cachable_instance.program)


def test_get_object_key_different_versions(cachable_instance):
    with patch("country_workspace.cache.manager.cache_manager.get_cache_version") as mock_version:
        mock_version.return_value = "1"
        key1 = cachable_instance.get_object_key()

        mock_version.return_value = "2"
        key2 = cachable_instance.get_object_key()

        assert key1 != key2
        assert "1" in key1
        assert "2" in key2
