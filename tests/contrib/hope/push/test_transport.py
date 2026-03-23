import pytest
from pytest_mock import MockerFixture

import country_workspace.contrib.hope.push.transport as tr
from country_workspace.contrib.hope.push.config import ROUTES
from country_workspace.exceptions import RemoteError


@pytest.mark.parametrize(
    ("method", "route", "args", "payload"),
    [
        ("create_rdi", tr.Route.CREATE, ({"a": 1},), {"a": 1}),
        ("post_individuals", tr.Route.INDIVIDUALS, ("RID", [{"x": 1}]), [{"x": 1}]),
        ("post_households", tr.Route.HOUSEHOLDS, ("RID", [{"x": 1}]), [{"x": 1}]),
        ("post_people", tr.Route.PEOPLE, ("RID", [{"x": 1}]), [{"x": 1}]),
        ("complete_rdi", tr.Route.COMPLETE, ("RID",), {}),
    ],
    ids=["create", "individuals", "households", "people", "complete"],
)
def test_hope_api_methods_delegate_to_client_post(
    mocker: MockerFixture,
    method: str,
    route: tr.Route,
    args: tuple,
    payload: object,
) -> None:
    client = mocker.MagicMock()
    client.post.return_value = {"ok": True}
    mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    assert getattr(api, method)(*args) == {"ok": True}
    client.post.assert_called_once_with(
        ROUTES[route].format(co_slug="CO", **({"rdi_id": args[0]} if route is not tr.Route.CREATE else {})),
        payload,
    )


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("create_rdi", ({"a": 1},)),
        ("post_individuals", ("RID", [])),
        ("post_households", ("RID", [])),
        ("post_people", ("RID", [])),
        ("complete_rdi", ("RID",)),
    ],
    ids=["create", "individuals", "households", "people", "complete"],
)
def test_hope_api_methods_propagate_remote_error(
    mocker: MockerFixture,
    method: str,
    args: tuple,
) -> None:
    client = mocker.MagicMock()
    client.post.side_effect = RemoteError("boom")
    mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    with pytest.raises(RemoteError, match="boom"):
        getattr(api, method)(*args)
