from collections import namedtuple
from typing import TYPE_CHECKING

from django.apps import apps
from django.contrib.auth.models import AnonymousUser

import pytest
from testutils.perms import user_grant_permissions

from country_workspace.state import state
from country_workspace.workspaces.backend import TenantBackend

if TYPE_CHECKING:
    from country_workspace.models import Office

_DATA = namedtuple("_DATA", "afg,ukr")

pytestmark = [pytest.mark.security, pytest.mark.django_db]


@pytest.fixture()
def data() -> _DATA:
    from testutils.factories import OfficeFactory

    with state.set(must_tenant=False):
        co1: "Office" = OfficeFactory(name="Afghanistan")
        co2: "Office" = OfficeFactory(name="Ukraine")
    return _DATA(co1, co2)


def pytest_generate_tests(metafunc):
    if "hope_model" in metafunc.fixturenames:
        models = list(apps.get_app_config("hope").get_models())
        metafunc.parametrize("hope_model", models)


@pytest.fixture()
def backend():
    return TenantBackend()


def test_aaa(backend, user):
    assert not backend.has_perm(user, "aaaa")


def test_anonymous(backend):
    assert not backend.has_perm(AnonymousUser(), "workspaces.view_countryhousehold")


def test_superuser(backend, data, admin_user):
    with state.set(tenant=data.afg):
        assert backend.has_perm(admin_user, "workspaces.view_countryhousehold")
        assert backend.has_module_perms(admin_user, "workspaces.view_countryhousehold")
        assert backend.get_available_modules(admin_user) == {"workspaces"}


def test_has_get_all_permissions_no_active_tenant(backend, data, user, admin_user):
    assert backend.get_all_permissions(user) == set()


def test_get_all_permissions_anonymous(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        assert backend.get_all_permissions(AnonymousUser()) == set()


def test_get_all_permissions_no_enabled_tenant(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        assert backend.get_all_permissions(user) == set()


def test_get_all_permissions_no_current_tenant(backend, data, user, admin_user):
    with user_grant_permissions(user, "workspaces.view_countryhousehold", country_office_or_program=data.ukr):
        assert backend.get_all_permissions(user) == set()


def test_get_all_permissions_valid_tenant(backend, data, user, django_assert_num_queries):
    with user_grant_permissions(user, "workspaces.view_countryhousehold", country_office_or_program=data.afg):
        with django_assert_num_queries(1):
            assert backend.get_all_permissions(user, data.afg) == {"workspaces.view_countryhousehold"}
            with django_assert_num_queries(0):
                # test cache
                assert backend.get_all_permissions(user, data.afg) == {"workspaces.view_countryhousehold"}


def test_get_all_permissions_superuser(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        assert backend.get_all_permissions(admin_user, data.afg)


def test_get_allowed_tenants_user(backend, data, user, rf):
    request = rf.get("/")
    request.user = user
    with user_grant_permissions(user, "workspaces.view_countryhousehold", country_office_or_program=data.afg):
        assert backend.get_allowed_tenants(request).count() == 1
        assert backend.get_allowed_tenants(request).first() == data.afg


def test_get_allowed_tenants_superuser(backend, data, admin_user, rf):
    request = rf.get("/")
    request.user = admin_user
    with state.set(tenant=data.afg, request=request):
        assert backend.get_allowed_tenants().count() == 2
        assert backend.get_allowed_tenants().first() == data.afg


def test_get_allowed_tenants_anon(backend, data, admin_user, rf):
    request = rf.get("/")
    request.user = AnonymousUser()
    with state.set(tenant=data.afg, request=request):
        assert backend.get_allowed_tenants().count() == 0
