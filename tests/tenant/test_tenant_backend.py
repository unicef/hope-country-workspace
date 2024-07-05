from collections import namedtuple
from typing import TYPE_CHECKING

from django.apps import apps
from django.contrib.auth.models import AnonymousUser

import pytest
from pytest_factoryboy import register
from testutils.factories import UserFactory
from testutils.perms import user_grant_permissions

from hope_country_workspace.state import state
from hope_country_workspace.tenant.backend import TenantBackend

if TYPE_CHECKING:
    from hope_country_workspace.security.models import CountryOffice

_DATA = namedtuple("_DATA", "afg,ukr")


register(UserFactory)


@pytest.fixture()
def data() -> _DATA:
    from testutils.factories import CountryOfficeFactory

    with state.set(must_tenant=False):
        co1: "CountryOffice" = CountryOfficeFactory(name="Afghanistan")
        co2: "CountryOffice" = CountryOfficeFactory(name="Ukraine")
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


def test_has_get_all_permissions_no_active_tenant(backend, data, user, admin_user):
    assert backend.get_all_permissions(user) == set()


def test_get_all_permissions_anonymous(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        assert backend.get_all_permissions(AnonymousUser()) == set()


def test_get_all_permissions_no_enabled_tenant(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        assert backend.get_all_permissions(user) == set()


def test_get_all_permissions_no_current_tenant(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        with user_grant_permissions(
            user, "hope_country_workspace.view_household", country_office=data.ukr
        ):
            assert backend.get_all_permissions(user) == set()


def test_get_all_permissions_valid_tenant(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        with user_grant_permissions(
            user, "hope_country_workspace.view_household", country_office=data.afg
        ):
            assert backend.get_all_permissions(user) == {
                "hope_country_workspace.view_household"
            }
            # test cache
            assert backend.get_all_permissions(user) == {
                "hope_country_workspace.view_household"
            }


def test_get_all_permissions_superuser(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        assert backend.get_all_permissions(admin_user)


def test_get_available_modules(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        with user_grant_permissions(
            user, "hope_country_workspace.view_household", country_office=data.afg
        ):
            assert backend.get_available_modules(user) == {"hope_country_workspace"}


def test_has_module_perms_no_active_tenant(backend, data, user, admin_user):
    with user_grant_permissions(
        user, "hope_country_workspace.view_household", country_office=data.afg
    ):
        assert not backend.has_module_perms(user, "hope_country_workspace")


def test_has_module_perms(backend, data, user, admin_user):
    with state.set(tenant=data.afg):
        with user_grant_permissions(
            user, "hope_country_workspace.view_household", country_office=data.afg
        ):
            assert backend.has_module_perms(user, "hope_country_workspace")


def test_has_module_perms_superuser(backend, data, admin_user):
    with state.set(tenant=data.afg):
        assert backend.has_module_perms(admin_user, "hope_country_workspace")


def test_get_allowed_tenants_user(backend, data, user, rf):
    request = rf.get("/")
    request.user = user
    with state.set(tenant=data.afg, request=request):
        with user_grant_permissions(
            user, "hope_country_workspace.view_household", country_office=data.afg
        ):
            assert backend.get_allowed_tenants().count() == 1
            assert backend.get_allowed_tenants().first() == data.afg


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
