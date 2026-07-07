from collections.abc import Callable
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.contrib.hope.push.config import Beneficiary, ERROR_CONFIG, ErrorConfig, RdiDeleteResult
from country_workspace.contrib.hope.push.processor import DedupProcessor, ProcessorBase, PushProcessor
from country_workspace.exceptions import RemoteError, RemoteUnavailableError

MOD = "country_workspace.contrib.hope.push.processor"

pytestmark = pytest.mark.django_db

# ----------------------------- processor base --------------------------


def test_ids_hint_short_and_long() -> None:
    assert ProcessorBase._ids_hint([]) == "[]"
    assert ProcessorBase._ids_hint([1, 2]) == "[1, 2]"

    ids = list(range(ERROR_CONFIG.MAX_IDS_HINT + 1))
    head = ", ".join(map(str, ids[: ERROR_CONFIG.MAX_IDS_HINT]))
    assert ProcessorBase._ids_hint(ids) == f"[{head}, …]"


def test_err_truncates_and_caps(mocker: MockerFixture) -> None:
    mocker.patch(
        f"{MOD}.ERROR_CONFIG",
        ErrorConfig(MAX_ERRORS=3, MAX_ERROR_LEN=5, MAX_IDS_HINT=5, MARKER="marker"),
    )
    processor = ProcessorBase()

    processor._err("abcdef")
    processor._err("x")
    processor._err("y")
    processor._err("z")

    assert processor.total["errors"] == ["abcd…", "x", "marker"]


# ----------------------------- serializer ------------------------------


def test_serializer_cached_once(mocker: MockerFixture, processor: PushProcessor) -> None:
    serializer = mocker.MagicMock()
    spy = mocker.patch(f"{MOD}.serializer_for_program", return_value=serializer)

    assert processor.serializer is serializer
    assert processor.serializer is serializer

    spy.assert_called_once_with(processor.program_hope_id)


# ------------------------------ preflight ------------------------------


def test_preflight_collects_preflight_errors(mocker: MockerFixture, processor: PushProcessor, err_contains) -> None:
    processor.master_detail, processor.pks, processor.rdp_id = True, [1, 2], 10
    spy = mocker.patch(f"{MOD}.preflight_errors", return_value=["boom-1", "boom-2"])

    processor.preflight()

    spy.assert_called_once_with(
        pks=[1, 2],
        master_detail=True,
        exclude_rdp_ids=(10,),
    )
    assert err_contains(processor.total["errors"], "boom-1")
    assert err_contains(processor.total["errors"], "boom-2")


def test_preflight_empty_is_ok(mocker: MockerFixture, processor: PushProcessor) -> None:
    spy = mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    processor.preflight()

    spy.assert_called_once_with(
        pks=processor.pks,
        master_detail=processor.master_detail,
        exclude_rdp_ids=(processor.rdp_id,),
    )
    assert processor.total["errors"] == []


# ------------------------------- RDI ops -------------------------------


@pytest.mark.parametrize(
    ("country_workspace_id", "expected_extra"),
    [
        ("ds-1", {"country_workspace_id": "ds-1"}),
        (None, {}),
    ],
    ids=["with_country_workspace_id", "without_country_workspace_id"],
)
def test_rdi_create_success(
    mocker: MockerFixture,
    processor: PushProcessor,
    country_workspace_id: str | None,
    expected_extra: dict,
) -> None:
    processor.country_workspace_id = country_workspace_id
    spy = mocker.patch.object(processor.api, "create_rdi", return_value={"id": "RID-1"})
    mocker.patch(f"{MOD}.existing_hope_rdi_id", return_value=None)

    processor.rdi_create()

    assert processor.hope_rdi_id == "RID-1"
    spy.assert_called_once_with(
        {
            "name": processor.batch_name,
            "program": processor.program_hope_id,
            "imported_by_email": processor.imported_by_email,
            **expected_extra,
        }
    )


def test_rdi_create_logs_missing_id(mocker: MockerFixture, processor: PushProcessor, err_contains) -> None:
    mocker.patch.object(processor.api, "create_rdi", return_value={"foo": "bar"})
    mocker.patch(f"{MOD}.existing_hope_rdi_id", return_value=None)

    processor.rdi_create()

    assert processor.hope_rdi_id is None
    assert err_contains(processor.total["errors"], "can't create: no id in response")


def test_rdi_create_returns_early_when_try_remote_failed(
    mocker: MockerFixture,
    processor: PushProcessor,
) -> None:
    spy_fail = mocker.patch.object(processor, "fail")
    mocker.patch.object(processor, "try_remote", return_value=None)
    mocker.patch(f"{MOD}.existing_hope_rdi_id", return_value=None)

    processor.rdi_create()

    assert processor.hope_rdi_id is None
    spy_fail.assert_not_called()


@pytest.mark.parametrize("delete_error", [False, True], ids=["delete_ok", "delete_failed"])
def test_rdi_create_deletes_existing_rdi_before_create(
    mocker: MockerFixture,
    processor: PushProcessor,
    delete_error: bool,
    err_contains,
) -> None:
    mocker.patch(f"{MOD}.existing_hope_rdi_id", return_value="OLD-RDI")
    delete = mocker.patch.object(
        processor.api,
        "delete_rdi",
        return_value=RdiDeleteResult.DELETED,
        side_effect=RemoteError("boom") if delete_error else None,
    )
    create = mocker.patch.object(processor.api, "create_rdi", return_value={"id": "NEW-RDI"})

    processor.rdi_create()

    delete.assert_called_once_with("OLD-RDI")
    if delete_error:
        create.assert_not_called()
        assert processor.hope_rdi_id == "OLD-RDI"
        assert err_contains(processor.total["errors"], "request failed")
    else:
        create.assert_called_once()
        assert processor.hope_rdi_id == "NEW-RDI"


def test_rdi_create_keeps_already_merged_rdi(mocker: MockerFixture, processor: PushProcessor) -> None:
    mocker.patch(f"{MOD}.existing_hope_rdi_id", return_value="OLD-RDI")
    mocker.patch.object(processor.api, "delete_rdi", return_value=RdiDeleteResult.ALREADY_MERGED)
    create = mocker.patch.object(processor.api, "create_rdi")

    processor.rdi_create()

    assert processor.hope_rdi_id == "OLD-RDI"
    assert processor.rdi_already_merged is True
    create.assert_not_called()


def test_rdi_create_clears_deleted_rdi_id_when_create_failed(
    mocker: MockerFixture,
    processor: PushProcessor,
    err_contains,
) -> None:
    mocker.patch(f"{MOD}.existing_hope_rdi_id", return_value="OLD-RDI")
    mocker.patch.object(processor.api, "delete_rdi", return_value=RdiDeleteResult.DELETED)
    mocker.patch.object(processor.api, "create_rdi", side_effect=RemoteError("boom"))

    processor.rdi_create()

    assert processor.hope_rdi_id is None
    assert err_contains(processor.total["errors"], "request failed")


@pytest.mark.parametrize("rid", [None, "RID-1"], ids=["no_rdi", "has_rdi"])
def test_rdi_complete_paths(
    mocker: MockerFixture,
    processor: PushProcessor,
    rid: str | None,
    err_contains,
) -> None:
    processor.hope_rdi_id = rid
    spy = mocker.patch.object(processor, "run_remote", return_value=True)

    processor.rdi_complete()

    if rid is None:
        spy.assert_not_called()
        assert err_contains(processor.total["errors"], "can't complete")
    else:
        spy.assert_called_once()
        assert spy.call_args.args[0] == "RDI"


# ------------------------- rdi_push_* delegate -------------------------


@pytest.mark.parametrize(
    ("method", "label"),
    [("rdi_push_households", "Households"), ("rdi_push_individuals", "Individuals"), ("rdi_push_people", "People")],
    ids=["households", "individuals", "people"],
)
def test_rdi_push_methods_delegate(mocker: MockerFixture, processor: PushProcessor, method: str, label: str) -> None:
    spy = mocker.patch.object(processor, "_push_batched")

    getattr(processor, method)()

    spy.assert_called_once()
    assert spy.call_args.args[0] == label


# ----------------------------- batching --------------------------------


def test_push_batched_happy_path(mocker: MockerFixture, processor: PushProcessor, qs: Callable[[list], object]) -> None:
    processor.hope_rdi_id = "RID-1"
    processor.queryset = qs([1])

    prepare = mocker.Mock(return_value=([1], [{"n": 1}]))
    post = mocker.Mock(return_value={"ok": True})
    process = mocker.MagicMock()

    processor._push_batched("People", prepare, post, process)

    prepare.assert_called_once()
    post.assert_called_once_with("RID-1", [{"n": 1}])
    process.assert_called_once_with({"ok": True}, [1])


def test_push_batched_requires_context(
    processor: PushProcessor,
    err_contains,
) -> None:
    processor.total = {"errors": []}
    processor.queryset = None
    processor.hope_rdi_id = None

    processor._push_batched("People", lambda _: ([], []), lambda *_: {}, lambda *_: None)
    assert err_contains(processor.total["errors"], "hope_rdi_id is not set")

    processor.hope_rdi_id = "RID-1"
    processor._push_batched("People", lambda _: ([], []), lambda *_: {}, lambda *_: None)
    assert err_contains(processor.total["errors"], "queryset is not set")


def test_push_batched_skips_empty_payload(
    mocker: MockerFixture,
    processor: PushProcessor,
    qs: Callable[[list], object],
) -> None:
    processor.hope_rdi_id = "RID-1"
    processor.queryset = qs([1])

    prepare = mocker.Mock(return_value=([], []))
    post = mocker.MagicMock()
    process = mocker.MagicMock()
    spy_try_remote = mocker.patch.object(processor, "try_remote")

    processor._push_batched("People", prepare, post, process)

    prepare.assert_called_once()
    spy_try_remote.assert_not_called()
    post.assert_not_called()
    process.assert_not_called()


def test_push_batched_skips_processing_when_remote_failed(
    mocker: MockerFixture,
    processor: PushProcessor,
    qs: Callable[[list], object],
) -> None:
    processor.hope_rdi_id = "RID-1"
    processor.queryset = qs([1])

    prepare = mocker.Mock(return_value=([1], [{"n": 1}]))
    post = mocker.MagicMock()
    process = mocker.MagicMock()
    mocker.patch.object(processor, "try_remote", return_value=None)

    processor._push_batched("People", prepare, post, process)

    prepare.assert_called_once()
    post.assert_not_called()
    process.assert_not_called()


def test_push_batched_stops_when_prepare_added_errors(
    mocker: MockerFixture,
    processor: PushProcessor,
    qs: Callable[[list], object],
) -> None:
    processor.hope_rdi_id = "RID-1"
    processor.queryset = qs([1])

    def prepare(_: object) -> tuple[list[int], list[dict]]:
        processor._err("mapping failed")
        return [1], [{"n": 1}]

    post = mocker.MagicMock()
    process = mocker.MagicMock()
    spy_try_remote = mocker.patch.object(processor, "try_remote")

    processor._push_batched("Households", prepare, post, process)

    assert processor.total["errors"] == ["mapping failed"]
    spy_try_remote.assert_not_called()
    post.assert_not_called()
    process.assert_not_called()


@pytest.mark.parametrize(
    ("method_name", "expected_result"),
    [
        ("try_remote", None),
        ("run_remote", False),
    ],
    ids=["try_remote", "run_remote"],
)
@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_remote_helpers_collect_errors(
    mocker: MockerFixture,
    processor: PushProcessor,
    err_contains,
    method_name: str,
    expected_result: object,
    exc_cls: type[Exception],
) -> None:
    fn = mocker.Mock(side_effect=exc_cls("boom"))

    result = getattr(processor, method_name)("People", fn, ids=[10, 20])

    assert result is expected_result
    assert err_contains(processor.total["errors"], "request failed. boom")
    assert err_contains(processor.total["errors"], "ids=[10, 20]")
    fn.assert_called_once_with()


# ---------------------------- prepare_* --------------------------------


def test_prepare_households_batch_uses_mapping_and_serializer(
    only_master_detail,
    mocker: MockerFixture,
    processor: PushProcessor,
    serializer_identity: PushProcessor,
    no_blob_sync: PushProcessor,
    beneficiary_stub: Callable[..., Beneficiary],
) -> None:
    fields = HOUSEHOLD_ROLE_REF_FIELDS

    mocker.patch(
        f"{MOD}.map_role_value",
        side_effect=lambda ind_map, _err, _hh_pk, _key, value: ind_map.get(value),
    )
    mocker.patch(
        f"{MOD}.map_members",
        side_effect=lambda ind_map, _err, _hh_pk, ids: [ind_map[i] for i in ids],
    )

    members = [beneficiary_stub(id=1), beneficiary_stub(id=2)]
    hh = beneficiary_stub(pk=777, prefetched_members=members)
    hh._group = {
        fields.head_of_household: 1,
        fields.primary_collector: None,
        fields.alternate_collector: None,
        "keep": "x",
        "drop": None,
    }

    processor.ind_id_map = {1: "IND-1.1", 2: "IND-2.1"}

    ids, payload = processor._prepare_households_batch([hh])

    assert ids == [777]
    assert payload == [
        {
            fields.head_of_household: "IND-1.1",
            "members": ["IND-1.1", "IND-2.1"],
            "keep": "x",
            "originating_id": 777,
        }
    ]


def test_prepare_households_batch_uses_members_queryset_when_not_prefetched(
    only_master_detail,
    mocker: MockerFixture,
    processor: PushProcessor,
    serializer_identity: PushProcessor,
    no_blob_sync: PushProcessor,
    beneficiary_stub: Callable[..., Beneficiary],
) -> None:
    mocker.patch(f"{MOD}.HOUSEHOLD_ROLE_REF_FIELDS", ())
    mocker.patch(f"{MOD}.map_members", return_value=["IND-1.1", "IND-2.1"])

    hh = beneficiary_stub(pk=777)
    hh._group = {"keep": "x", "drop": None}
    hh.members = mocker.MagicMock()
    hh.members.values_list.return_value = [1, 2]

    ids, payload = processor._prepare_households_batch([hh])

    assert ids == [777]
    assert payload == [{"keep": "x", "members": ["IND-1.1", "IND-2.1"], "originating_id": 777}]
    hh.members.values_list.assert_called_once_with("id", flat=True)


def test_prepare_individuals_batch_injects_id(
    only_master_detail,
    processor: PushProcessor,
    serializer_identity: PushProcessor,
    no_blob_sync: PushProcessor,
    beneficiary_stub: Callable[..., Beneficiary],
) -> None:
    i1 = beneficiary_stub(id=10, _group={"a": 1})
    i2 = beneficiary_stub(id=11, _group={"b": 2})

    ids, rows = processor._prepare_individuals_batch([i1, i2])

    assert ids == [10, 11]
    assert rows == [
        {"a": 1, "country_workspace_id": 10, "originating_id": 10},
        {"b": 2, "country_workspace_id": 11, "originating_id": 11},
    ]


def test_prepare_people_batch_plain(
    only_people_only,
    processor: PushProcessor,
    serializer_identity: PushProcessor,
    no_blob_sync: PushProcessor,
    beneficiary_stub: Callable[..., Beneficiary],
) -> None:
    i1 = beneficiary_stub(id=10, _group={"a": 1})
    i2 = beneficiary_stub(id=11, _group={"b": 2})

    ids, rows = processor._prepare_people_batch([i1, i2])

    assert ids == [10, 11]
    assert rows == [
        {"a": 1, "country_workspace_id": 10, "originating_id": 10},
        {"b": 2, "country_workspace_id": 11, "originating_id": 11},
    ]


# ------------------------- response handlers ---------------------------


@pytest.mark.parametrize(
    ("resp", "ids", "ok"),
    [
        ({"processed": 2, "accepted": 2}, [1, 2], True),
        ({"processed": 1, "accepted": 0}, [9], False),
        ({"errors": 2, "processed": 2, "accepted": 0, "results": [{}, {}]}, [141, 153], False),
        ({}, [9], False),
    ],
    ids=["all_accepted", "accepted_mismatch", "remote_errors", "unexpected"],
)
def test_process_households_response_paths(
    only_master_detail,
    processor: PushProcessor,
    resp: dict,
    ids: list[int],
    ok: bool,
    err_contains,
) -> None:
    processor.total = {"errors": []}
    processor._process_households_response(resp, ids)

    if ok:
        assert processor.total["households"] == 2
    else:
        assert any(
            err_contains(processor.total["errors"], text)
            for text in ("accepted mismatch", "remote returned errors", "unexpected response")
        )


def test_process_individuals_response_paths(
    only_master_detail,
    mocker: MockerFixture,
    processor: PushProcessor,
    err_contains,
) -> None:
    processor.total = {"errors": []}
    load_mapping = mocker.patch(
        f"{MOD}.load_mapping_from_api",
        side_effect=[
            {1: "IND-1.1", 2: "IND-2.1"},
            {999: "IND-999.1"},
        ],
    )

    processor._process_individuals_response(
        {"processed": 2, "accepted": 2, "individual_id_mapping": {"1": "IND-1.1", "2": "IND-2.1"}},
        [1, 2],
    )
    assert processor.total["individuals"] == 2
    assert processor.ind_id_map == {1: "IND-1.1", 2: "IND-2.1"}

    processor._process_individuals_response(
        {"processed": 1, "accepted": 1, "individual_id_mapping": {"999": "IND-999.1"}},
        [1, 2],
    )
    assert err_contains(processor.total["errors"], "accepted mismatch")
    assert processor.total["individuals"] == 2
    assert processor.ind_id_map == {1: "IND-1.1", 2: "IND-2.1"}

    processor.total["errors"].clear()
    processor._process_individuals_response({"errors": 1, "processed": 1, "accepted": 0, "results": [{}]}, [1])
    assert err_contains(processor.total["errors"], "remote returned errors")

    processor.total["errors"].clear()
    processor._process_individuals_response({}, [1])
    assert err_contains(processor.total["errors"], "unexpected response")

    assert load_mapping.call_count == 1


def test_individuals_mapping_accumulates_across_batches(
    only_master_detail, mocker: MockerFixture, processor: PushProcessor
) -> None:
    mocker.patch(f"{MOD}.load_mapping_from_api", side_effect=[{1: "IND-1.1"}, {2: "IND-2.1"}])

    processor._process_individuals_response(
        {"processed": 1, "accepted": 1, "individual_id_mapping": {"1": "IND-1.1"}},
        [1],
    )
    processor._process_individuals_response(
        {"processed": 1, "accepted": 1, "individual_id_mapping": {"2": "IND-2.1"}},
        [2],
    )

    assert processor.ind_id_map == {1: "IND-1.1", 2: "IND-2.1"}
    assert processor.total["individuals"] == 2


@pytest.mark.parametrize(
    ("resp", "ids", "ok"),
    [
        ({"id": "rdi-x", "people": [{}, {}]}, [1, 2], True),
        ({"id": "rdi-y", "people": [{}]}, [1], False),
        ({"id": "rdi-x", "people": [{}]}, [1, 2], False),
        ({"errors": 1, "processed": 1, "accepted": 0, "results": [{}]}, [1], False),
        ({"id": "rdi-x", "people": {}}, [1], False),
    ],
    ids=["ok", "rdi_mismatch", "people_len_mismatch", "remote_errors", "unexpected"],
)
def test_process_people_response_paths(
    only_people_only,
    processor: PushProcessor,
    resp: dict,
    ids: list[int],
    ok: bool,
    err_contains,
) -> None:
    processor.total = {"errors": []}
    processor.hope_rdi_id = "rdi-x"

    processor._process_people_response(resp, ids)

    if ok:
        assert processor.total["people"] == 2
    else:
        assert any(
            err_contains(processor.total["errors"], text)
            for text in ("remote returned errors", "rdi mismatch", "people length mismatch", "unexpected response")
        )


@pytest.mark.parametrize(
    ("resp", "expected"),
    [({"errors": ["x"]}, True), ({"errors": 0}, False), ({"ok": True}, False)],
    ids=["has_errors", "errors_zero", "ok"],
)
def test_resp_err(processor: PushProcessor, resp: dict, expected: bool) -> None:
    assert processor._resp_err("T", resp, [1]) is expected


def test_resp_err_keeps_only_error_results(processor: PushProcessor) -> None:
    response = {
        "id": "RID-1",
        "processed": 2,
        "accepted": 1,
        "errors": 1,
        "results": [{"pk": 1, "foo": "ok"}, {"pk": 2, "errors": ["bad"]}],
    }

    assert processor._resp_err("People", response, [1, 2]) is True

    error = processor.total["errors"][0]
    assert "remote returned errors" in error
    assert "errors_only" in error
    assert "{'pk': 2, 'errors': ['bad']}" in error
    assert "{'pk': 1, 'foo': 'ok'}" not in error


# ------------------------------- queryset ------------------------------


def test_using_qs_restores_previous(processor: PushProcessor, qs: Callable[[list], object]) -> None:
    previous = qs([1])
    current = qs([2])
    processor.queryset = previous

    with processor._using_qs(current):
        assert processor.queryset is current

    assert processor.queryset is previous


def test_run_with_uses_temporary_queryset(
    mocker: MockerFixture,
    processor: PushProcessor,
    qs: Callable[[list], object],
) -> None:
    queryset = qs([1])
    step = mocker.MagicMock()

    processor.run_with(queryset, step)

    assert processor.queryset is None
    step.assert_called_once_with()


# ------------------------------ dedup ----------------------------------


def test_dedup_run_without_deduplication_set_id(dedup_processor: DedupProcessor, err_contains) -> None:
    dedup_processor.rdp.deduplication_set_id = None

    dedup_processor.run()

    assert dedup_processor.total["images_sent"] == 0
    assert dedup_processor.total["deduplication_set_id"] is None
    assert err_contains(dedup_processor.total["errors"], "deduplication_set_id: is not set")


def test_dedup_run_creates_new_set_when_de_can_create(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    dedup_api_cm,
) -> None:
    ds_id = uuid4()
    dedup_processor.rdp.deduplication_set_id = ds_id

    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = True
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    deduplicate = mocker.patch.object(dedup_processor, "deduplicate", return_value=3)

    dedup_processor.run()

    make_client.assert_called_once_with(dedup_processor.group_reference_id, deduplication_set_id=str(ds_id))
    client.can_create_deduplication_set.assert_called_once_with()
    deduplicate.assert_called_once_with(client, ds_id, notification_url=None)
    client.process.assert_not_called()
    assert dedup_processor.total["images_sent"] == 3
    assert dedup_processor.total["deduplication_set_id"] == str(ds_id)


def test_dedup_run_processes_existing_set_when_de_cannot_create(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    dedup_api_cm,
) -> None:
    ds_id = uuid4()
    dedup_processor.rdp.deduplication_set_id = ds_id

    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = False
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    run_remote = mocker.patch.object(dedup_processor, "run_remote", return_value=True)
    deduplicate = mocker.patch.object(dedup_processor, "deduplicate")

    dedup_processor.run()

    make_client.assert_called_once_with(dedup_processor.group_reference_id, deduplication_set_id=str(ds_id))
    client.can_create_deduplication_set.assert_called_once_with()
    run_remote.assert_called_once_with("process_existing_deduplication_set", client.process)
    deduplicate.assert_not_called()
    assert dedup_processor.total["images_sent"] == 0
    assert dedup_processor.total["deduplication_set_id"] == str(ds_id)


def test_dedup_run_returns_when_can_create_check_failed(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    dedup_api_cm,
) -> None:
    ds_id = uuid4()
    dedup_processor.rdp.deduplication_set_id = ds_id

    client = mocker.MagicMock()
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    mocker.patch.object(dedup_processor, "try_remote", return_value=None)
    deduplicate = mocker.patch.object(dedup_processor, "deduplicate")
    run_remote = mocker.patch.object(dedup_processor, "run_remote")

    dedup_processor.run()

    make_client.assert_called_once_with(dedup_processor.group_reference_id, deduplication_set_id=str(ds_id))
    deduplicate.assert_not_called()
    run_remote.assert_not_called()
    assert dedup_processor.total["images_sent"] == 0
    assert dedup_processor.total["deduplication_set_id"] == str(ds_id)


def test_iter_images_filters_empty_and_non_strings(
    dedup_processor: DedupProcessor,
    individuals_with_photo: tuple,
) -> None:
    with_photo, _ = individuals_with_photo

    assert list(dedup_processor._iter_images()) == [
        {"reference_pk": str(with_photo.pk), "filename": with_photo.hope_blob_key("photo")},
    ]


def test_create_deduplication_set_success(mocker: MockerFixture, dedup_processor: DedupProcessor) -> None:
    client = mocker.MagicMock()
    ds_id = uuid4()
    client.create_deduplication_set.return_value = {"id": str(ds_id)}

    assert dedup_processor.create_deduplication_set(client, ds_id) is True


def test_create_deduplication_set_returns_false_when_remote_failed(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
) -> None:
    client = mocker.MagicMock()
    ds_id = uuid4()
    mocker.patch.object(dedup_processor, "try_remote", return_value=None)

    assert dedup_processor.create_deduplication_set(client, ds_id) is False


@pytest.mark.parametrize(
    "payload",
    [{}, {"id": ""}, {"id": None}, {"id": "other-id"}],
    ids=["empty", "blank_id", "none_id", "mismatch"],
)
def test_create_deduplication_set_logs_id_mismatch(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    payload: dict,
    err_contains,
) -> None:
    client = mocker.MagicMock()
    ds_id = uuid4()
    client.create_deduplication_set.return_value = payload

    assert dedup_processor.create_deduplication_set(client, ds_id) is False
    assert err_contains(dedup_processor.total["errors"], "response id mismatch")


def test_upload_images_success(mocker: MockerFixture, dedup_processor: DedupProcessor) -> None:
    mocker.patch.object(
        dedup_processor,
        "_iter_images",
        return_value=iter(
            [
                {"reference_pk": "1", "filename": "a.jpg"},
                {"reference_pk": "2", "filename": "b.jpg"},
            ]
        ),
    )
    client = mocker.MagicMock()

    assert dedup_processor.upload_images(client) == (True, 2)

    client.create_images.assert_called_once_with(
        [
            {"reference_pk": "1", "filename": "a.jpg"},
            {"reference_pk": "2", "filename": "b.jpg"},
        ]
    )
    client.ready.assert_called_once_with()


def test_upload_images_fails_without_images(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    err_contains,
) -> None:
    mocker.patch.object(dedup_processor, "_iter_images", return_value=iter(()))
    client = mocker.MagicMock()

    assert dedup_processor.upload_images(client) == (False, 0)

    assert err_contains(dedup_processor.total["errors"], "no images to deduplicate")
    client.create_images.assert_not_called()
    client.ready.assert_not_called()


@pytest.mark.parametrize(
    ("failed_method", "expected"),
    [
        ("create_images", (False, 0)),
        ("ready", (False, 1)),
    ],
    ids=["create_images_error", "ready_error"],
)
def test_upload_images_stops_on_remote_error(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    failed_method: str,
    expected: tuple[bool, int],
) -> None:
    mocker.patch.object(
        dedup_processor,
        "_iter_images",
        return_value=iter([{"reference_pk": "1", "filename": "a.jpg"}]),
    )
    client = mocker.MagicMock()
    getattr(client, failed_method).side_effect = RemoteError("boom")

    assert dedup_processor.upload_images(client) == expected
    assert dedup_processor.total["errors"]

    client.create_images.assert_called_once_with([{"reference_pk": "1", "filename": "a.jpg"}])
    if failed_method == "create_images":
        client.ready.assert_not_called()
    else:
        client.ready.assert_called_once_with()


def test_deduplicate_stops_when_create_set_failed(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
) -> None:
    client = mocker.MagicMock()
    ds_id = uuid4()
    mocker.patch.object(dedup_processor, "create_deduplication_set", return_value=False)
    upload_images = mocker.patch.object(dedup_processor, "upload_images")

    assert dedup_processor.deduplicate(client, ds_id) == 0

    upload_images.assert_not_called()
    client.process.assert_not_called()


def test_deduplicate_stops_when_upload_failed(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
) -> None:
    client = mocker.MagicMock()
    ds_id = uuid4()

    mocker.patch.object(dedup_processor, "create_deduplication_set", return_value=True)
    mocker.patch.object(dedup_processor, "upload_images", return_value=(False, 1))

    assert dedup_processor.deduplicate(client, ds_id) == 1

    client.process.assert_not_called()


@pytest.mark.parametrize(
    "process_error",
    [False, True],
    ids=["success", "process_error"],
)
def test_deduplicate_process_result(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    process_error: bool,
    err_contains,
) -> None:
    client = mocker.MagicMock()
    if process_error:
        client.process.side_effect = RemoteError("boom")

    ds_id = uuid4()
    mocker.patch.object(dedup_processor, "create_deduplication_set", return_value=True)
    mocker.patch.object(dedup_processor, "upload_images", return_value=(True, 2))

    assert dedup_processor.deduplicate(client, ds_id) == 2

    client.process.assert_called_once_with()

    if process_error:
        assert err_contains(dedup_processor.total["errors"], "request failed. boom")
    else:
        assert dedup_processor.total["errors"] == []


def test_dedup_run_passes_notification_url_to_deduplicate(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    dedup_api_cm,
) -> None:
    from uuid import uuid4

    ds_id = uuid4()
    dedup_processor.rdp.deduplication_set_id = ds_id

    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = True
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    deduplicate = mocker.patch.object(dedup_processor, "deduplicate", return_value=0)

    dedup_processor.run(notification_url="https://cw.example.org/callback/token/")

    deduplicate.assert_called_once_with(client, ds_id, notification_url="https://cw.example.org/callback/token/")


def test_dedup_run_without_notification_url_passes_none(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
    dedup_api_cm,
) -> None:
    from uuid import uuid4

    ds_id = uuid4()
    dedup_processor.rdp.deduplication_set_id = ds_id

    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = True
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    deduplicate = mocker.patch.object(dedup_processor, "deduplicate", return_value=0)

    dedup_processor.run()

    deduplicate.assert_called_once_with(client, ds_id, notification_url=None)


def test_create_deduplication_set_passes_notification_url_to_client(
    mocker: MockerFixture,
    dedup_processor: DedupProcessor,
) -> None:
    from uuid import uuid4

    client = mocker.MagicMock()
    ds_id = uuid4()
    client.create_deduplication_set.return_value = {"id": str(ds_id)}

    result = dedup_processor.create_deduplication_set(
        client, ds_id, notification_url="https://cw.example.org/callback/token/"
    )

    assert result is True
    client.create_deduplication_set.assert_called_once_with(notification_url="https://cw.example.org/callback/token/")
