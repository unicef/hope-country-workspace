from collections.abc import Generator
from unittest.mock import MagicMock, Mock

import pytest
from pytest_mock import MockFixture
from requests import HTTPError

from country_workspace.contrib.kobo.api.common import DataGetter

URL = "https://test.org"
CACHE_TTL = 42


@pytest.fixture
def cache_mock(mocker: MockFixture) -> Mock:
    return mocker.patch("country_workspace.contrib.kobo.api.common.cache")


@pytest.fixture
def session_mock() -> Generator[Mock, None, None]:
    return MagicMock(name="Session()")


@pytest.fixture
def cached_response_class_mock(mocker: MockFixture) -> Mock:
    return mocker.patch("country_workspace.contrib.kobo.api.common.CachedResponse")


@pytest.fixture
def data_getter_cache_key_mock(mocker: MockFixture) -> Mock:
    return mocker.patch("country_workspace.contrib.kobo.api.common.data_getter_cache_key")


def test_cache_can_be_skipped(cache_mock: Mock, session_mock: Mock) -> None:
    function = MagicMock()
    function.return_value = True

    data_getter = DataGetter(
        session=session_mock,
        cache_ttl=CACHE_TTL,
        do_not_use_cache_if=function,
    )
    response = data_getter(URL)

    assert response == session_mock.get.return_value
    session_mock.get.assert_called_with(URL, headers=None)
    function.assert_called_once_with(URL)
    cache_mock.assert_not_called()


def test_cached_value_is_returned(
    cache_mock: Mock, session_mock: Mock, cached_response_class_mock: Mock, data_getter_cache_key_mock: Mock
) -> None:
    data_getter = DataGetter(
        session=session_mock,
        cache_ttl=CACHE_TTL,
    )
    response = data_getter(URL)

    assert response == cached_response_class_mock.return_value
    cached_response_class_mock.assert_called_once_with(cache_mock.get.return_value)
    session_mock.get.assert_not_called()
    cache_mock.get.assert_called_once_with(data_getter_cache_key_mock.return_value)
    data_getter_cache_key_mock.assert_called_once_with(URL)


def test_failing_response_is_not_cached(cache_mock: Mock, session_mock: Mock) -> None:
    cache_mock.get.return_value = None
    session_mock.get.return_value.raise_for_status.side_effect = HTTPError()

    data_getter = DataGetter(
        session=session_mock,
        cache_ttl=CACHE_TTL,
    )
    response = data_getter(URL)

    assert response == session_mock.get.return_value
    cache_mock.set.assert_not_called()


def test_response_is_cached(
    cache_mock: Mock, session_mock: Mock, cached_response_class_mock: Mock, data_getter_cache_key_mock: Mock
) -> None:
    cache_mock.get.return_value = None

    data_getter = DataGetter(
        session=session_mock,
        cache_ttl=CACHE_TTL,
    )
    response = data_getter(URL)

    assert response == session_mock.get.return_value
    cache_mock.set.assert_called_once_with(
        data_getter_cache_key_mock.return_value,
        {
            "json": session_mock.get.return_value.json.return_value,
            "status_code": session_mock.get.return_value.status_code,
        },
        CACHE_TTL,
    )


def test_non_json_response_is_not_cached(cache_mock: Mock, session_mock: Mock) -> None:
    cache_mock.get.return_value = None
    session_mock.get.return_value.json.side_effect = ValueError("not json")

    data_getter = DataGetter(
        session=session_mock,
        cache_ttl=CACHE_TTL,
    )
    response = data_getter(URL)

    assert response == session_mock.get.return_value
    cache_mock.set.assert_not_called()
