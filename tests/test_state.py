from django.core.signing import get_cookie_signer
from django.http import HttpResponse

import pytest

from country_workspace.state import State, state
from country_workspace.workspaces.config import conf
from country_workspace.workspaces.utils import RequestHandler


@pytest.fixture()
def tenant_user(afghanistan, reporters):
    """User with access to a tenant"""
    from testutils.factories import UserFactory, UserRoleFactory

    u = UserFactory(username="user", is_staff=False, is_superuser=False, is_active=True)
    UserRoleFactory(country_office=afghanistan, group=reporters, user=u)
    return u


@pytest.fixture()
def req(rf, tenant_user):
    signer = get_cookie_signer()

    req = rf.get("/")
    req.user = tenant_user
    req.COOKIES[conf.COOKIE_NAME] = signer.sign(
        tenant_user.roles.first().country_office.slug
    )
    yield req


def test_set():
    s = State()
    s.tenant = 1
    with s.set(tenant=2, k=1):
        assert s.tenant == 2
    assert s.tenant == 1
    assert not hasattr(s, "k")


def test_configure():
    s = State()
    s.tenant = 1
    with s.configure(x=1):
        assert s.tenant is None
        assert s.x == 1
    assert not hasattr(s, "x")
    assert s.tenant == 1


def test_set_cookie():
    s = State()
    s.add_cookies("test", "1")
    assert s.cookies["test"] == ["1", None, None, "/", None, False, False, None]
    r = HttpResponse()
    s.set_cookies(r)
    assert r.cookies["test"]


def test_handler_request(req):
    with state.configure():
        h = RequestHandler()
        h.process_request(req)
        assert state.request == req
        assert state.tenant_cookie == req.user.roles.first().country_office.slug


def test_handler_response(req):
    response = HttpResponse()
    with state.configure(tenant="abc", x=123):
        h = RequestHandler()
        h.process_response(req, response)
        assert state.tenant is None
        assert state.request is None
        assert state.tenant_cookie is None
        assert state.x == 123
