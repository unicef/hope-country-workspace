import pytest
from pytest_mock import MockerFixture

import country_workspace.contrib.hope.push.transport as tr
from country_workspace.contrib.hope.push.config import ROUTES
from country_workspace.exceptions import RemoteError


@pytest.mark.parametrize(
    ("method", "route", "args", "payload", "format_kwargs"),
    [
        ("create_rdi", tr.Route.CREATE_RDI, ({"a": 1},), {"a": 1}, {}),
        ("post_individuals", tr.Route.INDIVIDUALS, ("RID", [{"x": 1}]), [{"x": 1}], {"rdi_id": "RID"}),
        ("post_households", tr.Route.HOUSEHOLDS, ("RID", [{"x": 1}]), [{"x": 1}], {"rdi_id": "RID"}),
        ("post_people", tr.Route.PEOPLE, ("RID", [{"x": 1}]), [{"x": 1}], {"rdi_id": "RID"}),
        ("complete_rdi", tr.Route.COMPLETE_RDI, ("RID",), {}, {"rdi_id": "RID"}),
    ],
    ids=["create", "individuals", "households", "people", "complete"],
)
def test_hope_api_post_methods_delegate_to_client_post(
    mocker: MockerFixture,
    method: str,
    route: tr.Route,
    args: tuple,
    payload: object,
    format_kwargs: dict[str, str],
) -> None:
    client = mocker.MagicMock()
    client.post.return_value = {"ok": True}
    hope_client_cls = mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    assert getattr(api, method)(*args) == {"ok": True}

    hope_client_cls.assert_called_once_with()
    client.post.assert_called_once_with(
        ROUTES[route].format(co_slug="CO", **format_kwargs),
        payload,
    )


def test_hope_api_delete_rdi_delegates_to_client_delete(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    client.delete.return_value = {"ok": True}
    hope_client_cls = mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    assert api.delete_rdi("RID") == {"ok": True}

    hope_client_cls.assert_called_once_with()
    client.delete.assert_called_once_with(ROUTES[tr.Route.DELETE_RDI].format(co_slug="CO", rdi_id="RID"))


@pytest.mark.parametrize(
    ("method", "args", "client_method"),
    [
        ("create_rdi", ({"a": 1},), "post"),
        ("post_individuals", ("RID", []), "post"),
        ("post_households", ("RID", []), "post"),
        ("post_people", ("RID", []), "post"),
        ("complete_rdi", ("RID",), "post"),
        ("delete_rdi", ("RID",), "delete"),
    ],
    ids=["create", "individuals", "households", "people", "complete", "delete"],
)
def test_hope_api_methods_propagate_remote_error(
    mocker: MockerFixture,
    method: str,
    args: tuple,
    client_method: str,
) -> None:
    client = mocker.MagicMock()
    getattr(client, client_method).side_effect = RemoteError("boom")
    hope_client_cls = mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    with pytest.raises(RemoteError, match="boom"):
        getattr(api, method)(*args)

    hope_client_cls.assert_called_once_with()
