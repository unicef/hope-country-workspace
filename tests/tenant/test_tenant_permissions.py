from typing import TYPE_CHECKING

import pytest

from hope_country_workspace.state import state

if TYPE_CHECKING:
    from django.contrib.auth.models import Group

    from hope_country_workspace.security.models import CountryOffice, UserRole
    from hope_country_workspace.types.http import AuthHttpRequest


@pytest.fixture()
def anonymous(request):
    from django.contrib.auth.models import AnonymousUser

    return AnonymousUser()


@pytest.fixture()
def tenant_user(request):
    from testutils.factories import CountryOfficeFactory, UserRoleFactory

    from hope_country_workspace.utils import get_or_create_defaults_group

    if "afghanistan" in request.fixturenames:
        co = request.getfixturevalue("afghanistan")
    else:
        co: "CountryOffice" = CountryOfficeFactory()
    g: "Group" = get_or_create_defaults_group()
    r: "UserRole" = UserRoleFactory(group=g, country_office=co)
    return r.user


@pytest.fixture()
def req(request, rf) -> "AuthHttpRequest":
    req: "AuthHttpRequest" = rf.get("/")
    current = state.request
    state.request = req
    yield req
    state.request = current


@pytest.mark.parametrize("u", ["tenant_user", "admin_user", "anonymous"])
def test_tenant_backend_get_allowed_tenants(
    request, afghanistan, req, u, django_assert_max_num_queries
):
    from hope_country_workspace.tenant.backend import TenantBackend

    req.user = request.getfixturevalue(u)
    b: TenantBackend = TenantBackend()

    # with django_assert_max_num_queries(1):
    if req.user.is_authenticated:
        assert list(b.get_allowed_tenants().values_list("pk", flat=True)) == [
            afghanistan.pk
        ]
    else:
        assert not b.get_allowed_tenants().values_list("pk", flat=True)


@pytest.mark.parametrize("u", ["tenant_user", "admin_user", "anonymous"])
def test_tenant_backend_get_all_permissions(
    request, afghanistan, req, u, django_assert_max_num_queries
):
    from hope_country_workspace.tenant.backend import TenantBackend

    req.user = request.getfixturevalue(u)
    b: TenantBackend = TenantBackend()
    if hasattr(req.user, "_tenant_%s_perm_cache" % afghanistan.pk):
        delattr(req.user, "_tenant_%s_perm_cache" % afghanistan.pk)

    with state.set(tenant=afghanistan):
        with django_assert_max_num_queries(2):
            if req.user.is_authenticated:
                assert b.get_all_permissions(req.user)
                with django_assert_max_num_queries(0):
                    assert b.get_all_permissions(req.user)
            else:
                assert not b.get_all_permissions(req.user)
                with django_assert_max_num_queries(0):
                    assert not b.get_all_permissions(req.user)


def test_tenant_backend_get_all_permissions_no_tenant(
    request, afghanistan, req, tenant_user, django_assert_max_num_queries
):
    from hope_country_workspace.tenant.backend import TenantBackend

    req.user = tenant_user
    b: TenantBackend = TenantBackend()
    if hasattr(req.user, "_tenant_%s_perm_cache" % afghanistan.pk):
        delattr(req.user, "_tenant_%s_perm_cache" % afghanistan.pk)

    with django_assert_max_num_queries(1):
        assert not b.get_all_permissions(req.user)
