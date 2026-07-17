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
    hope_client_cls = mocker.patch.object(tr, "HopeClient", return_value=client)

    api = tr.HopeApi(co_slug="CO")

    assert api.delete_rdi("RID") is tr.RdiDeleteResult.DELETED

    hope_client_cls.assert_called_once_with()
    client.delete.assert_called_once_with(ROUTES[tr.Route.DELETE_RDI].format(co_slug="CO", rdi_id="RID"))


@pytest.mark.parametrize(
    ("status_code", "error_code", "expected"),
    [
        (404, None, tr.RdiDeleteResult.DELETED),
        (409, tr.RDI_ALREADY_MERGED_ERROR_CODE, tr.RdiDeleteResult.ALREADY_MERGED),
    ],
    ids=["not_found", "already_merged"],
)
def test_hope_api_delete_rdi_handles_response_error(
    mocker: MockerFixture,
    status_code: int,
    error_code: str | None,
    expected: tr.RdiDeleteResult,
) -> None:
    response = mocker.MagicMock(status_code=status_code)
    response.json.return_value = {"error": error_code}
    client = mocker.MagicMock()
    client.delete.side_effect = tr.HopeResponseError("boom", response=response)
    mocker.patch.object(tr, "HopeClient", return_value=client)

    assert tr.HopeApi(co_slug="CO").delete_rdi("RID") is expected


def test_hope_api_delete_rdi_propagates_unhandled_response_error(mocker: MockerFixture) -> None:
    response = mocker.MagicMock(status_code=409)
    response.json.return_value = {"error": "rdi_merge_in_progress"}
    error = tr.HopeResponseError("boom", response=response)
    client = mocker.MagicMock()
    client.delete.side_effect = error
    mocker.patch.object(tr, "HopeClient", return_value=client)

    with pytest.raises(tr.HopeResponseError) as exc_info:
        tr.HopeApi(co_slug="CO").delete_rdi("RID")

    assert exc_info.value is error


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
