from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser

import pytest

from country_workspace.state import state
from country_workspace.workspaces.backend import TenantBackend


@pytest.fixture()
def backend(db):
    return TenantBackend()


@pytest.fixture()
def user(db):
    from testutils.factories import UserFactory

    return UserFactory()


@pytest.fixture()
def office(db):
    from testutils.factories import OfficeFactory

    return OfficeFactory()


def test_get_all_permissions(backend, user, office):
    assert not backend.get_all_permissions(user)
    with state.activate_tenant(office):
        assert not backend.get_all_permissions(user)
        assert not backend.get_all_permissions(AnonymousUser())


def test_get_allowed_tenants(backend, user):
    assert not backend.get_allowed_tenants(Mock())


def test_has_module_perms(backend, user):
    assert not backend.has_module_perms(user, "country_workspace")


def test_has_perm(backend, user):
    assert not backend.has_perm(user, "country_workspace.view_household")


def test_get_available_modules(backend, user):
    assert not backend.get_available_modules(user)
