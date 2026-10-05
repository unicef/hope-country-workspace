import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError
from country_workspace.rdp.push import processor as processor_mod
from country_workspace.rdp.push.processor import ERROR_CONFIG, PushProcessor


pytestmark = pytest.mark.django_db


@pytest.fixture
def push_processor(push_config, mocker: MockerFixture) -> PushProcessor:
    mocker.patch.object(processor_mod, "HopeApi")
    return PushProcessor(push_config)


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        ([], "[]"),
        ([1, 2], "[1, 2]"),
        ([1, 2, 3, 4, 5, 6], "[1, 2, 3, 4, 5, …]"),
    ],
)
def test_ids_hint(ids: list[int], expected: str) -> None:
    assert PushProcessor._ids_hint(ids) == expected


def test_err_truncates_and_caps_errors(push_processor: PushProcessor) -> None:
    push_processor._err("x" * (ERROR_CONFIG.MAX_ERROR_LEN + 10))

    assert len(push_processor.total["errors"][0]) == ERROR_CONFIG.MAX_ERROR_LEN
    assert push_processor.total["errors"][0].endswith("…")

    push_processor.total["errors"] = ["error"] * (ERROR_CONFIG.MAX_ERRORS - 1)
    push_processor._err("another")

    assert push_processor.total["errors"][-1] == ERROR_CONFIG.MARKER

    errors = push_processor.total["errors"].copy()
    push_processor._err("ignored")
    assert push_processor.total["errors"] == errors


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("try_remote", "result"),
        ("run_remote", True),
    ],
)
def test_remote_helpers_succeed(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    method: str,
    expected: object,
) -> None:
    fn = mocker.Mock(return_value="result")

    assert getattr(push_processor, method)("Subject", fn) == expected
    fn.assert_called_once_with()


@pytest.mark.parametrize("method", ["try_remote", "run_remote"])
def test_remote_helpers_collect_errors(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    method: str,
) -> None:
    fn = mocker.Mock(side_effect=RemoteError("remote"))

    result = getattr(push_processor, method)("Subject", fn, ids=[1])

    assert result in {None, False}
    assert "remote" in push_processor.total["errors"][0]


def test_preflight(push_processor: PushProcessor, mocker: MockerFixture) -> None:
    preflight_errors = mocker.patch.object(processor_mod, "preflight_errors", return_value=["first", "second"])

    push_processor.preflight()

    preflight_errors.assert_called_once_with(
        pks=push_processor.pks,
        master_detail=push_processor.master_detail,
        exclude_rdp_ids=(push_processor.rdp_id,),
    )
    assert len(push_processor.total["errors"]) == 2


def test_rdi_complete_without_rdi(push_processor: PushProcessor) -> None:
    push_processor.rdi_complete()

    assert push_processor.has_errors is True
    push_processor.api.complete_rdi.assert_not_called()


def test_rdi_complete(push_processor: PushProcessor) -> None:
    push_processor.hope_rdi_id = "RID"

    push_processor.rdi_complete()

    push_processor.api.complete_rdi.assert_called_once_with("RID")


@pytest.mark.parametrize(
    ("country_workspace_id", "included"),
    [("CW", True), (None, False)],
)
def test_rdi_create(
    push_processor: PushProcessor,
    country_workspace_id: str | None,
    included: bool,
) -> None:
    push_processor.country_workspace_id = country_workspace_id
    push_processor.api.create_rdi.return_value = {"id": "RID"}

    push_processor.rdi_create()

    assert push_processor.hope_rdi_id == "RID"
    payload = push_processor.api.create_rdi.call_args.args[0]
    assert ("country_workspace_id" in payload) is included


def test_rdi_create_rejects_invalid_response(push_processor: PushProcessor) -> None:
    push_processor.api.create_rdi.return_value = {"id": 123}

    push_processor.rdi_create()

    assert push_processor.hope_rdi_id is None
    assert push_processor.has_errors is True


def test_rdi_create_stops_on_remote_failure(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(push_processor, "try_remote", return_value=None)

    push_processor.rdi_create()

    assert push_processor.hope_rdi_id is None


@pytest.mark.parametrize(
    ("method", "name", "prepare_name", "post_name", "process_name"),
    [
        (
            "rdi_push_households",
            "Households",
            "_prepare_households_batch",
            "post_households",
            "_process_households_response",
        ),
        (
            "rdi_push_individuals",
            "Individuals",
            "_prepare_individuals_batch",
            "post_individuals",
            "_process_individuals_response",
        ),
        (
            "rdi_push_people",
            "People",
            "_prepare_people_batch",
            "post_people",
            "_process_people_response",
        ),
    ],
)
def test_push_methods_delegate_to_batched(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    method: str,
    name: str,
    prepare_name: str,
    post_name: str,
    process_name: str,
) -> None:
    push_batched = mocker.patch.object(push_processor, "_push_batched")

    getattr(push_processor, method)()

    push_batched.assert_called_once_with(
        name,
        getattr(push_processor, prepare_name),
        getattr(push_processor.api, post_name),
        getattr(push_processor, process_name),
    )


def test_run_with_restores_queryset_on_error(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    original = mocker.MagicMock()
    current = mocker.MagicMock()
    step = mocker.Mock(side_effect=RuntimeError("failed"))
    push_processor.queryset = original

    with pytest.raises(RuntimeError, match="failed"):
        push_processor.run_with(current, step)

    assert push_processor.queryset is original


@pytest.mark.parametrize("method", ["_prepare_individuals_batch", "_prepare_people_batch"])
def test_prepare_people_rows(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    method: str,
) -> None:
    individual = mocker.MagicMock(id=1, originating_id="OID")
    individual.apply_grouping.return_value = {"name": "John"}
    serializer = mocker.Mock(side_effect=lambda rows: rows)
    push_processor.__dict__["serializer"] = serializer

    ids, payload = getattr(push_processor, method)([individual])

    assert ids == [1]
    assert payload == [{"name": "John", "country_workspace_id": 1, "originating_id": "OID"}]


@pytest.mark.parametrize("prefetched", [True, False])
def test_prepare_households_batch(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    prefetched: bool,
) -> None:
    mocker.patch.object(processor_mod, "HOUSEHOLD_ROLE_REF_FIELDS", ("role",))
    map_role = mocker.patch.object(processor_mod, "map_role_value", return_value="ROLE")
    map_members = mocker.patch.object(processor_mod, "map_members", return_value=["MEMBER"])

    member = mocker.MagicMock(id=2)
    household = mocker.MagicMock(id=1, pk=1, originating_id="OID")
    household.apply_grouping.return_value = {"role": 2, "empty": None}
    household.prefetched_members = [member] if prefetched else None
    household.members.values_list.return_value = [2]

    push_processor.__dict__["serializer"] = mocker.Mock(side_effect=lambda rows: rows)

    ids, payload = push_processor._prepare_households_batch([household])

    assert ids == [1]
    assert payload == [
        {
            "role": "ROLE",
            "members": ["MEMBER"],
            "originating_id": "OID",
        }
    ]
    map_role.assert_called_once()
    map_members.assert_called_once()


@pytest.mark.parametrize(
    ("method", "response", "key"),
    [
        ("_process_households_response", {"processed": 2, "accepted": 2}, "households"),
        (
            "_process_individuals_response",
            {"processed": 2, "accepted": 2, "individual_id_mapping": {}},
            "individuals",
        ),
        ("_process_people_response", {"id": "RID", "people": [{}, {}]}, "people"),
    ],
)
def test_process_response_success(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    method: str,
    response: dict,
    key: str,
) -> None:
    push_processor.hope_rdi_id = "RID"
    mocker.patch.object(processor_mod, "load_mapping_from_api", return_value={1: "IND"})

    getattr(push_processor, method)(response, [1, 2])

    assert push_processor.total[key] == 2
    if key == "individuals":
        assert push_processor.ind_id_map == {1: "IND"}


@pytest.mark.parametrize(
    "method",
    [
        "_process_households_response",
        "_process_individuals_response",
        "_process_people_response",
    ],
)
def test_process_response_rejects_unexpected_payload(
    push_processor: PushProcessor,
    method: str,
) -> None:
    push_processor.hope_rdi_id = "RID"

    getattr(push_processor, method)({"unexpected": True}, [1])

    assert push_processor.has_errors is True


@pytest.mark.parametrize(
    ("method", "response"),
    [
        ("_process_households_response", {"processed": 2, "accepted": 1}),
        (
            "_process_individuals_response",
            {"processed": 2, "accepted": 1, "individual_id_mapping": {}},
        ),
    ],
)
def test_process_response_rejects_accepted_mismatch(
    push_processor: PushProcessor,
    method: str,
    response: dict,
) -> None:
    getattr(push_processor, method)(response, [1, 2])

    assert push_processor.has_errors is True


@pytest.mark.parametrize(
    "response",
    [
        {"id": "OTHER", "people": [{}, {}]},
        {"id": "RID", "people": [{}]},
    ],
)
def test_process_people_response_rejects_mismatch(
    push_processor: PushProcessor,
    response: dict,
) -> None:
    push_processor.hope_rdi_id = "RID"

    push_processor._process_people_response(response, [1, 2])

    assert push_processor.has_errors is True


def test_resp_err_filters_accepted_results(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    fail = mocker.patch.object(push_processor, "fail")
    response = {
        "id": "RID",
        "processed": 2,
        "accepted": 1,
        "errors": {"field": ["invalid"]},
        "results": [
            {"pk": 1, "name": "accepted"},
            {"pk": 2, "name": ["invalid"]},
        ],
    }

    assert push_processor._resp_err("People", response, [1, 2]) is True

    logged = fail.call_args.kwargs["response"]
    assert logged["results"] == [{"pk": 2, "name": ["invalid"]}]
    assert logged["_log_view"] == "errors_only"


@pytest.mark.parametrize("missing", ["rdi", "queryset"])
def test_push_batched_requires_context(
    push_processor: PushProcessor,
    mocker: MockerFixture,
    missing: str,
) -> None:
    push_processor.hope_rdi_id = None if missing == "rdi" else "RID"
    push_processor.queryset = None
    prepare = mocker.Mock()
    post = mocker.Mock()
    process = mocker.Mock()

    push_processor._push_batched("People", prepare, post, process)

    assert push_processor.has_errors is True
    post.assert_not_called()


def test_push_batched_skips_empty_payload(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    push_processor.hope_rdi_id = "RID"
    push_processor.queryset = mocker.MagicMock()
    push_processor.queryset.iterator.return_value = iter(["first", "second"])
    mocker.patch.object(processor_mod, "PUSH_BATCH_SIZE", 1)
    prepare = mocker.Mock(side_effect=[([1], []), ([2], [{"value": 2}])])
    post = mocker.Mock(return_value={"ok": True})
    process = mocker.Mock()

    push_processor._push_batched("People", prepare, post, process)

    post.assert_called_once_with("RID", [{"value": 2}])
    process.assert_called_once_with({"ok": True}, [2])


def test_push_batched_stops_on_prepare_error(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    push_processor.hope_rdi_id = "RID"
    push_processor.queryset = mocker.MagicMock()
    push_processor.queryset.iterator.return_value = iter([1])

    def prepare(_batch):
        push_processor.fail("People", "invalid")
        return [1], [{"value": 1}]

    post = mocker.Mock()

    push_processor._push_batched("People", prepare, post, mocker.Mock())

    post.assert_not_called()


def test_push_batched_stops_on_remote_failure(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    push_processor.hope_rdi_id = "RID"
    push_processor.queryset = mocker.MagicMock()
    push_processor.queryset.iterator.return_value = iter([1])
    prepare = mocker.Mock(return_value=([1], [{"value": 1}]))
    mocker.patch.object(push_processor, "try_remote", return_value=None)
    process = mocker.Mock()

    push_processor._push_batched("People", prepare, mocker.Mock(), process)

    process.assert_not_called()


def test_serializer_is_cached(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    serializer = mocker.Mock()
    resolve = mocker.patch.object(processor_mod, "serializer_for_program", return_value=serializer)

    assert push_processor.serializer is serializer
    assert push_processor.serializer is serializer

    resolve.assert_called_once_with(push_processor.program_hope_id)


def test_resp_err_keeps_response_without_results_list(
    push_processor: PushProcessor,
    mocker: MockerFixture,
) -> None:
    fail = mocker.patch.object(push_processor, "fail")
    response = {"errors": {"field": ["invalid"]}}

    assert push_processor._resp_err("People", response, [1]) is True

    assert fail.call_args.kwargs["response"] is response
