import pytest
from json import JSONDecodeError
from requests.exceptions import RequestException, HTTPError
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
def test_methods_delegate_and_build_url(mocker, routes, err, method, route, args, expected_payload):
    client = mocker.MagicMock()
    client.post.return_value = {"ok": True}
    mocker.patch.object(tr, "HopeClient", return_value=client)
    api = tr.HopeApi(co_slug="CO", err=err)
    out = getattr(api, method)(*args)

    called_url, called_payload = client.post.call_args.args
    suffix = routes[route].format(co_slug="CO", rdi_id=(args[0] if args else ""))
    assert called_url.endswith(suffix)
    assert called_payload == expected_payload
    assert out == {"ok": True}


@pytest.mark.parametrize(
    ("exc", "method", "args", "route"),
    [
        (RequestException("boom"), "create_rdi", ({"a": 1},), tr.Route.CREATE),
        (JSONDecodeError("bad json", "{}", 1), "post_individuals", ("RID", []), tr.Route.INDIVIDUALS),
        (RemoteError("remote"), "complete_rdi", ("RID",), tr.Route.COMPLETE),
    ],
    ids=["requests", "json", "remote"],
)
def test_errors_are_captured_and_none_returned(mocker, routes, errs, err, exc, method, args, route):
    client = mocker.MagicMock()
    client.post.side_effect = exc
    mocker.patch.object(tr, "HopeClient", return_value=client)
    api = tr.HopeApi(co_slug="CO", err=err)
    out = getattr(api, method)(*args)

    assert out is None
    assert errs
    assert errs[-1].startswith("Hope API:")
    assert route.value in errs[-1]


def test_dedup_api_proxies_non_callable_attr(mocker, err):
    client = mocker.MagicMock()
    client.program_id = "X"

    cm = mocker.MagicMock(__enter__=mocker.Mock(return_value=client), __exit__=mocker.Mock(return_value=False))
    mocker.patch.object(tr, "make_client", return_value=cm)

    with tr.dedup_api("PROGRAM", err) as de:
        assert de.program_id == "X"


@pytest.mark.parametrize(
    ("method", "setup", "expected", "expect_error_log"),
    [
        ("foo", lambda c: setattr(c.foo, "return_value", None), True, False),
        ("foo", lambda c: setattr(c.foo, "side_effect", ValueError("bad")), None, True),
        ("status", None, "SENTINEL", False),
    ],
    ids=["none_to_true", "error_logs_none", "status_404_sentinel_no_log"],
)
def test_dedup_api_proxy_behaviour(mocker, errs, err, method, setup, expected, expect_error_log):
    client = mocker.MagicMock()

    if method == "status":
        resp = mocker.MagicMock(status_code=HTTP_404_NOT_FOUND)
        client.status.side_effect = HTTPError(response=resp)
    else:
        setup(client)

    cm = mocker.MagicMock(__enter__=mocker.Mock(return_value=client), __exit__=mocker.Mock(return_value=False))
    mocker.patch.object(tr, "make_client", return_value=cm)

    before = list(errs)
    with tr.dedup_api("PROGRAM", err) as de:
        res = getattr(de, method)()
        if expected == "SENTINEL":
            assert res is de.DEDUPLICATION_SET_NOT_EXPOSED
        else:
            assert res == expected

    if expect_error_log:
        assert errs
        assert errs[-1].startswith(f"DedupEngine client.{method} failed:")
    else:
        assert errs == before
