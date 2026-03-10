import pytest
from requests.exceptions import HTTPError
from rest_framework.status import HTTP_404_NOT_FOUND
from country_workspace.exceptions import RemoteError

import country_workspace.contrib.hope.push.transport as tr
from country_workspace.contrib.hope.push.config import ROUTES


@pytest.fixture
def routes(mocker):
    mocker.patch.object(tr, "ROUTES", ROUTES)
    return ROUTES


@pytest.mark.parametrize(
    ("method", "route", "args", "expected_payload"),
    [
        ("create_rdi", tr.Route.CREATE, ({"a": 1},), {"a": 1}),
        ("post_individuals", tr.Route.INDIVIDUALS, ("RID", [{"x": 1}]), [{"x": 1}]),
        ("post_households", tr.Route.HOUSEHOLDS, ("RID", [{"h": 1}]), [{"h": 1}]),
        ("post_people", tr.Route.PEOPLE, ("RID", [{"p": 1}]), [{"p": 1}]),
        ("complete_rdi", tr.Route.COMPLETE, ("RID",), {}),
    ],
    ids=["create", "inds", "hhs", "people", "complete"],
)
def test_methods_delegate_and_build_url(mocker, routes, method, route, args, expected_payload):
    client = mocker.MagicMock()
    client.post.return_value = {"ok": True}
    mocker.patch.object(tr, "HopeClient", return_value=client)
    api = tr.HopeApi(co_slug="CO")
    out = getattr(api, method)(*args)

    called_url, called_payload = client.post.call_args.args
    suffix = routes[route].format(co_slug="CO", rdi_id=(args[0] if args else ""))
    assert called_url.endswith(suffix)
    assert called_payload == expected_payload
    assert out == {"ok": True}


@pytest.mark.parametrize(
    ("exc", "method", "args", "route"),
    [
        (RemoteError("boom"), "create_rdi", ({"a": 1},), tr.Route.CREATE),
        (RemoteError("boom"), "post_individuals", ("RID", []), tr.Route.INDIVIDUALS),
        (RemoteError("boom"), "complete_rdi", ("RID",), tr.Route.COMPLETE),
    ],
    ids=["create", "inds", "complete"],
)
def test_errors_are_propagated(mocker, routes, exc, method, args, route):
    client = mocker.MagicMock()
    client.post.side_effect = exc
    mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    with pytest.raises(RemoteError):
        getattr(api, method)(*args)

    called_url, _called_payload = client.post.call_args.args
    suffix = routes[route].format(co_slug="CO", rdi_id=(args[0] if args else ""))
    assert called_url.endswith(suffix)


def test_dedup_api_proxies_non_callable_attr(mocker):
    client = mocker.MagicMock()
    client.program_id = "X"

    cm = mocker.MagicMock(__enter__=mocker.Mock(return_value=client), __exit__=mocker.Mock(return_value=False))
    mocker.patch.object(tr, "make_client", return_value=cm)

    with tr.dedup_api("PROGRAM") as de:
        assert de.program_id == "X"


@pytest.mark.parametrize(
    ("method", "setup", "expected"),
    [
        ("foo", lambda c: setattr(c.foo, "return_value", None), True),
        ("foo", lambda c: setattr(c.foo, "side_effect", ValueError("bad")), "RAISE"),
        ("status", None, "SENTINEL"),
    ],
    ids=["none_to_true", "error_raises_remote", "status_404_sentinel"],
)
def test_dedup_api_proxy_behaviour(mocker, method, setup, expected):
    client = mocker.MagicMock()

    if method == "status":
        resp = mocker.MagicMock(status_code=HTTP_404_NOT_FOUND)
        client.status.side_effect = HTTPError(response=resp)
    else:
        setup(client)

    cm = mocker.MagicMock(__enter__=mocker.Mock(return_value=client), __exit__=mocker.Mock(return_value=False))
    mocker.patch.object(tr, "make_client", return_value=cm)

    with tr.dedup_api("PROGRAM") as de:
        if expected == "RAISE":
            with pytest.raises(RemoteError) as ei:
                getattr(de, method)()
            assert str(ei.value).startswith("DedupEngine: client.foo failed:")
        elif expected == "SENTINEL":
            assert getattr(de, method)() is de.DEDUPLICATION_SET_NOT_EXPOSED
        else:
            assert getattr(de, method)() == expected
