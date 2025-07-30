from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from country_workspace.cache.middleware import FetchFromCacheMiddleware, UpdateCacheMiddleware


@pytest.fixture
def fetch_middleware():
    get_response = MagicMock(return_value=HttpResponse())
    return FetchFromCacheMiddleware(get_response)


@pytest.fixture
def update_middleware():
    get_response = MagicMock(return_value=HttpResponse())
    return UpdateCacheMiddleware(get_response)


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.pk = 123
    return user


def test_fetch_middleware_none_cache_key(fetch_middleware, rf, mock_user):
    request = rf.get("/test-url/")
    request.user = mock_user

    with patch("country_workspace.cache.manager.cache_manager.build_key_from_request") as mock_build_key:
        mock_build_key.return_value = None

        response = fetch_middleware.process_request(request)

        assert response is None
        assert getattr(request, "_cache_update_cache", False) is True
        mock_build_key.assert_called_once_with(request, "view", mock_user.pk)


def test_fetch_middleware_non_get_request(fetch_middleware, rf, mock_user):
    request = rf.post("/test-url/")
    request.user = mock_user

    response = fetch_middleware.process_request(request)

    assert response is None
    assert getattr(request, "_cache_update_cache", True) is True


def test_fetch_middleware_with_etag(fetch_middleware, rf, mock_user):
    request = rf.get("/test-url/")
    request.user = mock_user
    cache_key = "test-cache-key"
    request.headers = {"etag": cache_key}

    with patch("country_workspace.cache.manager.cache_manager.build_key_from_request") as mock_build_key:
        mock_build_key.return_value = cache_key
        response = fetch_middleware.process_request(request)

        assert response.status_code == 304
        assert response.headers["Etag"] == cache_key


def test_fetch_middleware_no_cached_response(fetch_middleware, rf, mock_user):
    request = rf.get("/test-url/")
    request.user = mock_user
    cache_key = "test-cache-key"

    with (
        patch("country_workspace.cache.manager.cache_manager.build_key_from_request") as mock_build_key,
        patch("country_workspace.cache.manager.cache_manager.retrieve") as mock_retrieve,
    ):
        mock_build_key.return_value = cache_key
        mock_retrieve.return_value = None
        response = fetch_middleware.process_request(request)

        assert response is None
        assert getattr(request, "_cache_update_cache", False) is True
        mock_retrieve.assert_called_once_with(cache_key)


def test_fetch_middleware_anonymous_user(fetch_middleware, rf):
    request = rf.get("/test-url/")
    request.user = AnonymousUser()

    with patch("country_workspace.cache.manager.cache_manager.build_key_from_request") as mock_build_key:
        mock_build_key.return_value = None
        response = fetch_middleware.process_request(request)

        assert response is None
        mock_build_key.assert_called_once_with(request, "view", None)


def test_update_middleware_with_existing_etag(update_middleware, rf, mock_user):
    request = rf.get("/test-url/")
    request.user = mock_user
    request._cache_update_cache = True

    response = HttpResponse()
    response.status_code = 200
    existing_etag = "existing-etag-key"
    response.headers["Etag"] = existing_etag

    with patch("country_workspace.cache.manager.cache_manager.store") as mock_store:
        processed_response = update_middleware.process_response(request, response)

        mock_store.assert_called_once_with(existing_etag, response)
        assert processed_response.headers["Etag"] == existing_etag


def test_update_middleware_without_etag(update_middleware, rf, mock_user):
    request = rf.get("/test-url/")
    request.user = mock_user
    request._cache_update_cache = True

    response = HttpResponse()
    response.status_code = 200

    with (
        patch("country_workspace.cache.manager.cache_manager.build_key_from_request") as mock_build_key,
        patch("country_workspace.cache.manager.cache_manager.store") as mock_store,
    ):
        generated_key = "generated-cache-key"
        mock_build_key.return_value = generated_key
        processed_response = update_middleware.process_response(request, response)

        mock_build_key.assert_called_once_with(request, "view", mock_user.pk)
        mock_store.assert_called_once_with(generated_key, response)
        assert processed_response.headers["Etag"] == generated_key


def test_fetch_middleware_admin_action_request(fetch_middleware, rf, mock_user):
    request = rf.post("/test-url/", {"action": "validate_records"})
    request.user = mock_user

    response = fetch_middleware.process_request(request)

    assert response is None
    assert getattr(request, "_cache_update_cache", False) is True


def test_update_middleware_admin_action_request(update_middleware, rf, mock_user):
    request = rf.post("/test-url/", {"action": "validate_records"})
    request.user = mock_user
    request._cache_update_cache = True

    response = HttpResponse()
    response.status_code = 200

    processed_response = update_middleware.process_response(request, response)

    assert processed_response == response
