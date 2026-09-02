import pytest
from pytest_mock import MockerFixture

from country_workspace.rdp.constants import PUSH_BATCH_SIZE
from country_workspace.rdp.push.processor import PushProcessor
from country_workspace.rdp.push.types import PushWorkflowConfig

MOD = "country_workspace.rdp.push.processor"


@pytest.fixture
def config() -> PushWorkflowConfig:
    return {
        "batch_name": "RDP",
        "co_slug": "co",
        "imported_by_email": "user@example.org",
        "master_detail": False,
        "pks": [1, 2],
        "program_hope_id": "PROGRAM",
        "rdp_id": 7,
    }


@pytest.fixture
def processor(config: PushWorkflowConfig, mocker: MockerFixture) -> PushProcessor:
    mocker.patch(f"{MOD}.HopeApi")
    return PushProcessor(config)


def test_serializer_is_cached(processor: PushProcessor, mocker: MockerFixture) -> None:
    serializer = mocker.Mock()
    get_serializer = mocker.patch(f"{MOD}.serializer_for_program", return_value=serializer)

    assert processor.serializer is serializer
    assert processor.serializer is serializer
    get_serializer.assert_called_once_with("PROGRAM")


def test_preflight(processor: PushProcessor, mocker: MockerFixture) -> None:
    preflight = mocker.patch(f"{MOD}.preflight_errors", return_value=["first", "second"])

    processor.preflight()

    preflight.assert_called_once_with(pks=[1, 2], master_detail=False, exclude_rdp_ids=(7,))
    assert len(processor.total["errors"]) == 2


@pytest.mark.parametrize("rdi_id", [None, "RDI"], ids=["missing", "complete"])
def test_rdi_complete(processor: PushProcessor, rdi_id: str | None) -> None:
    processor.hope_rdi_id = rdi_id

    processor.rdi_complete()

    assert processor.has_errors is (rdi_id is None)
    assert processor.api.complete_rdi.called is (rdi_id is not None)


@pytest.mark.parametrize(
    "case",
    [
        (None, {"id": "RDI"}, "RDI", False),
        ("CW-ID", {"id": "RDI"}, "RDI", False),
        (None, {}, None, True),
        (None, {"id": 123}, None, True),
        (None, None, None, False),
    ],
    ids=["created", "workspace_id", "missing_id", "invalid_id", "no_response"],
)
def test_rdi_create(processor: PushProcessor, case) -> None:
    workspace_id, response, expected_id, has_errors = case
    processor.country_workspace_id = workspace_id
    processor.api.create_rdi.return_value = response

    processor.rdi_create()

    payload = {
        "name": "RDP",
        "program": "PROGRAM",
        "imported_by_email": "user@example.org",
        **({"country_workspace_id": workspace_id} if workspace_id else {}),
    }
    processor.api.create_rdi.assert_called_once_with(payload)
    assert processor.hope_rdi_id == expected_id
    assert processor.has_errors is has_errors


@pytest.mark.parametrize(
    "case",
    [
        ("rdi_push_households", "Households"),
        ("rdi_push_individuals", "Individuals"),
        ("rdi_push_people", "People"),
    ],
    ids=["households", "individuals", "people"],
)
def test_push_method_delegates(processor: PushProcessor, mocker: MockerFixture, case) -> None:
    method, name = case
    push = mocker.patch.object(processor, "_push_batched")

    getattr(processor, method)()

    assert push.call_args.args[0] == name


def test_run_with_restores_queryset(processor: PushProcessor, mocker: MockerFixture) -> None:
    previous, current = mocker.Mock(), mocker.Mock()
    processor.queryset = previous
    step = mocker.Mock(side_effect=lambda: processor.queryset is current)

    processor.run_with(current, step)

    step.assert_called_once_with()
    assert processor.queryset is previous


@pytest.mark.parametrize(
    "method", ["_prepare_individuals_batch", "_prepare_people_batch"], ids=["individuals", "people"]
)
def test_prepare_individuals(processor: PushProcessor, mocker: MockerFixture, method: str) -> None:
    first = mocker.Mock(id=1, originating_id="O1")
    second = mocker.Mock(id=2, originating_id="O2")
    first.apply_grouping.return_value = {"name": "A"}
    second.apply_grouping.return_value = {"name": "B"}
    mocker.patch(f"{MOD}.serializer_for_program", return_value=lambda rows: rows)

    ids, rows = getattr(processor, method)([first, second])

    assert ids == [1, 2]
    assert rows == [
        {"name": "A", "country_workspace_id": 1, "originating_id": "O1"},
        {"name": "B", "country_workspace_id": 2, "originating_id": "O2"},
    ]


@pytest.mark.parametrize("prefetched", [True, False], ids=["prefetched", "related_manager"])
def test_prepare_households(processor: PushProcessor, mocker: MockerFixture, prefetched: bool) -> None:
    member = mocker.Mock(id=2)
    household = mocker.Mock(id=1, pk=1, originating_id="O1")
    household.prefetched_members = [member] if prefetched else None
    household.members.values_list.return_value = [2]
    household.apply_grouping.return_value = {"role": 2, "empty": None}

    mocker.patch(f"{MOD}.HOUSEHOLD_ROLE_REF_FIELDS", ("role",))
    mocker.patch(f"{MOD}.map_role_value", return_value="IND-2")
    mocker.patch(f"{MOD}.map_members", return_value=["IND-2"])
    mocker.patch(f"{MOD}.serializer_for_program", return_value=lambda rows: rows)

    ids, rows = processor._prepare_households_batch([household])

    assert ids == [1]
    assert rows == [{"role": "IND-2", "members": ["IND-2"], "originating_id": "O1"}]


@pytest.mark.parametrize(
    "case",
    [
        ("households", {"processed": 2, "accepted": 2}, 2, False),
        ("households", {"processed": 2, "accepted": 1}, None, True),
        ("households", {"processed": "2", "accepted": 2}, None, True),
        (
            "individuals",
            {"processed": 2, "accepted": 2, "individual_id_mapping": {"1": "IND-1"}},
            2,
            False,
        ),
        (
            "individuals",
            {"processed": 2, "accepted": 1, "individual_id_mapping": {}},
            None,
            True,
        ),
        ("individuals", {"processed": 2, "accepted": 2}, None, True),
    ],
    ids=[
        "households_ok",
        "households_mismatch",
        "households_unexpected",
        "individuals_ok",
        "individuals_mismatch",
        "individuals_unexpected",
    ],
)
def test_process_group_response(processor: PushProcessor, mocker: MockerFixture, case) -> None:
    name, response, expected_count, has_errors = case
    mocker.patch(f"{MOD}.load_mapping_from_api", return_value={1: "IND-1"})

    getattr(processor, f"_process_{name}_response")(response, [1, 2])

    assert processor.total.get(name) == expected_count
    assert processor.has_errors is has_errors
    if name == "individuals" and expected_count:
        assert processor.ind_id_map == {1: "IND-1"}


@pytest.mark.parametrize(
    "case",
    [
        ({"id": "RDI", "people": [{}, {}]}, 2, False),
        ({"id": "OTHER", "people": [{}, {}]}, None, True),
        ({"id": "RDI", "people": [{}]}, None, True),
        ({"processed": 2}, None, True),
    ],
    ids=["ok", "rdi_mismatch", "length_mismatch", "unexpected"],
)
def test_process_people_response(processor: PushProcessor, case) -> None:
    response, expected_count, has_errors = case
    processor.hope_rdi_id = "RDI"

    processor._process_people_response(response, [1, 2])

    assert processor.total.get("people") == expected_count
    assert processor.has_errors is has_errors


@pytest.mark.parametrize("filtered", [False, True], ids=["raw", "errors_only"])
def test_response_errors(processor: PushProcessor, mocker: MockerFixture, filtered: bool) -> None:
    accepted = {"pk": 1, "name": "ok"}
    rejected = {"pk": 2, "errors": {"name": ["invalid"]}}
    response = {
        "id": "RDI",
        "processed": 2,
        "accepted": 1,
        "errors": ["invalid"],
        "results": [accepted, rejected] if filtered else None,
    }
    fail = mocker.patch.object(processor, "fail")

    assert processor._resp_err("People", response, [1, 2]) is True

    logged = fail.call_args.kwargs["response"]
    if filtered:
        assert logged["results"] == [rejected]
        assert logged["_log_view"] == "errors_only"
    else:
        assert logged is response


@pytest.mark.parametrize("missing", ["rdi", "queryset"], ids=["missing_rdi", "missing_queryset"])
def test_push_batched_requires_state(processor: PushProcessor, mocker: MockerFixture, missing: str) -> None:
    processor.hope_rdi_id = None if missing == "rdi" else "RDI"
    processor.queryset = mocker.Mock() if missing == "rdi" else None
    prepare = mocker.Mock()

    processor._push_batched("People", prepare, mocker.Mock(), mocker.Mock())

    assert processor.has_errors is True
    prepare.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        ([{"value": 1}], {"ok": True}, False, True, True),
        ([], None, False, False, False),
        ([{"value": 1}], {"ok": True}, True, False, False),
        ([{"value": 1}], None, False, True, False),
    ],
    ids=["success", "empty_payload", "prepare_errors", "no_response"],
)
def test_push_batched(processor: PushProcessor, mocker: MockerFixture, case) -> None:
    payload, response, has_errors, post_called, process_called = case
    processor.hope_rdi_id = "RDI"
    processor.queryset = qs = mocker.Mock()
    qs.iterator.return_value = [1, 2]
    processor.total["errors"] = ["existing"] if has_errors else []

    prepare = mocker.Mock(return_value=([1, 2], payload))
    post = mocker.Mock(return_value=response)
    process = mocker.Mock()

    processor._push_batched("People", prepare, post, process)

    qs.iterator.assert_called_once_with(chunk_size=PUSH_BATCH_SIZE)
    prepare.assert_called_once()
    assert post.called is post_called
    assert process.called is process_called
    if process_called:
        process.assert_called_once_with(response, [1, 2])
