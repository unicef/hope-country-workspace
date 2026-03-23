import pytest
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.processor import DedupProcessor, PushProcessor
from country_workspace.contrib.hope.push.config import Beneficiary, ErrorConfig
from country_workspace.exceptions import RemoteError
from country_workspace.models import Rdp


MOD = "country_workspace.contrib.hope.push.processor"


# ----------------------------- serializer ------------------------------


@pytest.mark.django_db
def test_serializer_cached_once(mocker: MockerFixture, processor: PushProcessor) -> None:
    def stub_ser(rows):
        return rows

    spy = mocker.patch(f"{MOD}.serializer_for_program", return_value=stub_ser)

    assert processor.serializer is processor.serializer
    spy.assert_called_once_with(processor.program_hope_id)


# ------------------------------ preflight ------------------------------


@pytest.mark.django_db
def test_preflight_collects_preflight_errors(mocker: MockerFixture, processor: PushProcessor) -> None:
    processor.master_detail, processor.pks, processor.rdp_id = True, [1, 2], 10

    msgs = ["boom-1", "boom-2"]
    spy = mocker.patch(f"{MOD}.preflight_errors", return_value=msgs)

    processor.preflight()

    spy.assert_called_once_with(pks=[1, 2], master_detail=True, exclude_rdp_id=10)
    assert processor.total["errors"] == [f"HopePush: Preflight: {m}" for m in msgs]


@pytest.mark.django_db
def test_preflight_empty_pks_is_ok(mocker: MockerFixture, processor: PushProcessor) -> None:
    processor.master_detail, processor.pks, processor.rdp_id = False, [], None

    spy = mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    processor.preflight()

    spy.assert_called_once_with(pks=[], master_detail=False, exclude_rdp_id=None)
    assert processor.total["errors"] == []


# ------------------------------- RDI ops -------------------------------


@pytest.mark.django_db
def test_rdi_create_success_and_failure(
    mocker: MockerFixture, processor: PushProcessor, err_contains: Callable[[list[str], str], bool]
) -> None:
    mocker.patch.object(processor.api, "create_rdi", side_effect=[{"id": "rdi-1"}, {"foo": "bar"}])

    processor.rdi_create()
    assert processor.hope_rdi_id == "rdi-1"

    processor.hope_rdi_id = None
    processor.rdi_create()
    assert err_contains(processor.total["errors"], "can't create")


@pytest.mark.django_db
def test_rdi_create_returns_early_when_try_remote_failed(
    mocker: MockerFixture,
    processor: PushProcessor,
) -> None:
    spy_fail = mocker.patch.object(processor, "fail")
    mocker.patch.object(processor, "try_remote", return_value=None)

    processor.rdi_create()

    assert processor.hope_rdi_id is None
    spy_fail.assert_not_called()


@pytest.mark.parametrize("rid", [None, "RID-1"], ids=["no_rdi", "has_rdi"])
def test_rdi_complete_paths(
    mocker: MockerFixture,
    processor: PushProcessor,
    rid: str | None,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    processor.hope_rdi_id = rid
    spy = mocker.patch.object(processor.api, "complete_rdi")

    processor.rdi_complete()

    if rid is not None:
        spy.assert_called_once_with(rid)
    else:
        spy.assert_not_called()
        assert err_contains(processor.total["errors"], "can't complete")


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


def test_push_batched_happy_path(mocker: MockerFixture, processor: PushProcessor, qs: Callable[[list], Any]) -> None:
    processor.hope_rdi_id = "rdi"
    processor.queryset = qs([1])

    def prepare(batch):
        return (list(batch), [{"n": i} for i in batch])

    post = mocker.MagicMock(return_value={"ok": True})
    proc = mocker.MagicMock()

    processor._push_batched("X", prepare, post, proc)

    post.assert_called_once_with("rdi", [{"n": 1}])
    proc.assert_called_once_with({"ok": True}, [1])


def test_push_batched_requires_context(
    processor: PushProcessor, err_contains: Callable[[list[str], str], bool]
) -> None:
    processor.total = {"errors": []}
    processor.queryset = None
    processor.hope_rdi_id = None

    processor._push_batched("X", lambda _: ([], []), lambda *_: {}, lambda *_: None)
    assert err_contains(processor.total["errors"], "hope_rdi_id is not set")

    processor.hope_rdi_id = "rdi"
    processor._push_batched("X", lambda _: ([], []), lambda *_: {}, lambda *_: None)
    assert err_contains(processor.total["errors"], "queryset is not set")


def test_push_batched_skips_empty_ids(
    mocker: MockerFixture,
    processor: PushProcessor,
    qs: Callable[[list], Any],
) -> None:
    processor.hope_rdi_id = "rdi"
    processor.queryset = qs([1])

    prepare = mocker.MagicMock(return_value=([], []))
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
    qs: Callable[[list], Any],
) -> None:
    processor.hope_rdi_id = "rdi"
    processor.queryset = qs([1])

    prepare = mocker.MagicMock(return_value=([1], [{"n": 1}]))
    post = mocker.MagicMock()
    process = mocker.MagicMock()
    mocker.patch.object(processor, "try_remote", return_value=None)

    processor._push_batched("People", prepare, post, process)

    prepare.assert_called_once()
    post.assert_not_called()
    process.assert_not_called()


def test_try_remote_returns_none_and_collects_error(
    processor: PushProcessor,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    result = processor.try_remote(
        "People",
        lambda: (_ for _ in ()).throw(RemoteError("boom")),
        ids=[10, 20],
    )

    assert result is None
    assert err_contains(processor.total["errors"], "request failed. boom")
    assert err_contains(processor.total["errors"], "ids=[10, 20]")


# ---------------------------- prepare_* --------------------------------


@pytest.mark.django_db
def test_prepare_households_batch_uses_mapping_and_serializer(
    mocker: MockerFixture,
    processor: PushProcessor,
    serializer_identity: Callable,
    beneficiary_stub: Callable[..., Beneficiary],
) -> None:
    mocker.patch(f"{MOD}.ROLE_FIELDS", ("head_of_household",))

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
    hh._group = {"head_of_household": members[0].id, "keep": "x", "drop": None}

    processor.ind_id_map = {m.id: f"IND-{m.id}.X" for m in members}

    ids, payload = processor._prepare_households_batch([hh])

    assert ids == [hh.id]
    assert payload == [
        {
            "head_of_household": "IND-1.X",
            "members": ["IND-1.X", "IND-2.X"],
            "keep": "x",
            "originating_id": hh.originating_id,
        }
    ]


def test_prepare_individuals_batch_injects_id(
    processor: PushProcessor, serializer_identity: Callable, beneficiary_stub: Callable[..., Beneficiary]
) -> None:
    i1, i2 = beneficiary_stub(id=10, _group={"a": 1}), beneficiary_stub(id=11, _group={"b": 2})

    ids, rows = processor._prepare_individuals_batch([i1, i2])

    assert ids == [10, 11]
    assert {"a": 1, "individual_id": 10, "originating_id": 10} in rows
    assert {"b": 2, "individual_id": 11, "originating_id": 11} in rows


def test_prepare_people_batch_plain(
    processor: PushProcessor, serializer_identity: Callable, beneficiary_stub: Callable[..., Beneficiary]
) -> None:
    i1, i2 = beneficiary_stub(id=10, _group={"a": 1}), beneficiary_stub(id=11, _group={"b": 2})

    ids, rows = processor._prepare_people_batch([i1, i2])

    assert ids == [10, 11]
    assert rows == [{"a": 1, "originating_id": 10}, {"b": 2, "originating_id": 11}]


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
    processor: PushProcessor,
    resp: dict,
    ids: list[int],
    ok: bool,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    processor.total = {"errors": []}
    processor._process_households_response(resp, ids)

    if ok:
        assert processor.total.get("households") == 2
    else:
        assert any(
            err_contains(processor.total["errors"], s)
            for s in ("accepted mismatch", "remote returned errors", "unexpected response")
        )


@pytest.mark.django_db
def test_process_individuals_response_paths(
    mocker: MockerFixture, processor: PushProcessor, err_contains: Callable[[list[str], str], bool]
) -> None:
    processor.total = {"errors": []}
    mocker.patch(f"{MOD}.load_mapping_from_api", return_value={1: "IND-1", 2: "IND-2"})

    processor._process_individuals_response(
        {"processed": 2, "accepted": 2, "individual_id_mapping": {"1": "IND-1", "2": "IND-2"}}, [1, 2]
    )
    assert processor.total.get("individuals") == 2
    assert processor.ind_id_map == {1: "IND-1", 2: "IND-2"}

    processor._process_individuals_response(
        {"processed": 1, "accepted": 1, "individual_id_mapping": {"1": "IND-1"}}, [1, 2]
    )
    assert err_contains(processor.total["errors"], "accepted mismatch")
    assert processor.total.get("individuals") == 3

    processor.total["errors"].clear()
    processor._process_individuals_response({"errors": 1, "processed": 1, "accepted": 0, "results": [{}]}, [1])
    assert err_contains(processor.total["errors"], "remote returned errors")

    processor.total["errors"].clear()
    processor._process_individuals_response({}, [1])
    assert err_contains(processor.total["errors"], "unexpected response")


@pytest.mark.django_db
def test_individuals_mapping_accumulates_across_batches(mocker: MockerFixture, processor: PushProcessor) -> None:
    mocker.patch(f"{MOD}.load_mapping_from_api", side_effect=[{1: "IND-1"}, {2: "IND-2"}])
    processor.total = {"errors": []}

    processor._process_individuals_response(
        {"processed": 1, "accepted": 1, "individual_id_mapping": {"1": "IND-1"}},
        [1],
    )
    processor._process_individuals_response(
        {"processed": 1, "accepted": 1, "individual_id_mapping": {"2": "IND-2"}},
        [2],
    )

    assert processor.ind_id_map == {1: "IND-1", 2: "IND-2"}
    assert processor.total.get("individuals") == 2


@pytest.mark.parametrize(
    ("resp", "ids", "ok"),
    [
        ({"id": "rdi-x", "people": [{}, {}]}, [1, 2], True),
        ({"id": "rdi-y", "people": [{}]}, [1], False),
        ({"id": "rdi-x", "people": [{}]}, [1, 2], False),
        ({"errors": 1, "processed": 1, "accepted": 0, "results": [{}]}, [1], False),
        ({"id": "rdi-x", "people": {}}, [1], False),
    ],
    ids=["ok_two_people", "rdi_mismatch", "people_len_mismatch", "remote_errors", "unexpected_response"],
)
def test_process_people_response_paths(
    processor: PushProcessor,
    resp: dict,
    ids: list[int],
    ok: bool,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    processor.total, processor.hope_rdi_id = {"errors": []}, "rdi-x"
    processor._process_people_response(resp, ids)

    if ok:
        assert processor.total.get("people") == 2
    else:
        assert any(
            err_contains(processor.total["errors"], s)
            for s in ("remote returned errors", "rdi mismatch", "people length mismatch", "unexpected response")
        )


@pytest.mark.parametrize(
    ("resp", "expected"),
    [({"errors": ["x"]}, True), ({"errors": 0}, False), ({"ok": True}, False)],
    ids=["has_errors", "errors_zero", "ok"],
)
def test_resp_err(processor: PushProcessor, resp: dict, expected: bool) -> None:
    processor.total = {"errors": []}
    assert processor._resp_err("T", resp, [1]) is expected


# ------------------------------- queryset ------------------------------


def test_using_qs_sets_and_restores(processor: PushProcessor, qs: Callable[[list], Any]) -> None:
    q = qs([1])
    assert processor.queryset is None

    with processor._using_qs(q):
        assert processor.queryset is q

    assert processor.queryset is None


def test_run_with_sets_qs_and_invokes_step(processor: PushProcessor, qs: Callable[[list], Any]) -> None:
    q = qs([1])
    called: list[bool] = []

    def step() -> None:
        assert processor.queryset is q
        called.append(True)

    processor.run_with(q, step)

    assert called == [True]
    assert processor.queryset is None


# ------------------------------- errors -------------------------------


@pytest.mark.django_db
def test__err_truncation_and_capping(mocker: MockerFixture, processor: PushProcessor) -> None:
    cfg = ErrorConfig(MAX_ERRORS=3, MAX_ERROR_LEN=10, MAX_IDS_HINT=5, MARKER="⟪TRUNC⟫")
    mocker.patch("country_workspace.contrib.hope.push.processor.ERROR_CONFIG", cfg)

    errs: list[str] = processor.total["errors"]
    assert errs == []

    processor._err("short")
    assert errs == ["short"]

    processor._err("x" * 20)
    assert errs[-1].endswith("…")
    assert len(errs[-1]) == 10

    processor._err("anything")
    assert errs[-1] == "⟪TRUNC⟫"
    assert len(errs) == 3

    processor._err("ignored")
    assert errs[-1] == "⟪TRUNC⟫"
    assert len(errs) == 3


@pytest.mark.django_db
def test_ids_hint_empty_and_truncated(mocker: MockerFixture) -> None:
    cfg = ErrorConfig(MAX_ERRORS=10, MAX_ERROR_LEN=200, MAX_IDS_HINT=2, MARKER="⟪TRUNC⟫")
    mocker.patch("country_workspace.contrib.hope.push.processor.ERROR_CONFIG", cfg)

    assert PushProcessor._ids_hint([]) == "[]"
    assert PushProcessor._ids_hint([1, 2, 3]) == "[1, 2, …]"


# ------------------------------ dedup ----------------------------------


@pytest.mark.parametrize(
    ("status", "dedup_run_state", "expected_error"),
    [
        (Rdp.PushStatus.SUCCESS, None, "can not run dedup in status"),
        (Rdp.PushStatus.PENDING, Rdp.DedupRunState.FINISHED, "already finished"),
    ],
    ids=["non_pending", "already_finished"],
)
def test_dedup_run_rejects_invalid_state(
    mocker: MockerFixture,
    err_contains: Callable[[list[str], str], bool],
    status: str,
    dedup_run_state: str | None,
    expected_error: str,
) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=status,
        dedup_run_state=dedup_run_state,
    )
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    proc = DedupProcessor(rdp_id=1)
    proc.run()

    assert err_contains(proc.total["errors"], expected_error)
    assert "rdp_id" not in proc.total


def test_dedup_run_with_no_images_sets_none(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    proc = DedupProcessor(rdp_id=1)
    mocker.patch.object(proc, "_collect_images", return_value=[])
    spy_deduplicate = mocker.patch.object(proc, "_deduplicate")

    proc.run()

    assert proc.total["deduplication_set_id"] is None
    spy_deduplicate.assert_not_called()


def test_dedup_run_success_sets_uuid(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    proc = DedupProcessor(rdp_id=1)
    images = [{"reference_pk": "10", "filename": "a.jpg"}, {"reference_pk": "11", "filename": "b.jpg"}]
    mocker.patch.object(proc, "_collect_images", return_value=images)

    ds_id = uuid4()
    mocker.patch.object(proc, "_deduplicate", return_value=ds_id)

    proc.run()

    assert proc.total["errors"] == []
    assert proc.total["images_sent"] == 2
    assert proc.total["deduplication_set_id"] == str(ds_id)


def test_collect_images_filters_blanks(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    pairs = [
        (100, None),
        (101, ""),
        (102, "   "),
        (103, " photo.jpg "),
    ]

    rows = mocker.MagicMock()
    rows.iterator.return_value = iter(pairs)

    qs = mocker.MagicMock()
    qs.values_list.return_value = rows

    mocker.patch(f"{MOD}.individuals_for_rdp", return_value=qs)

    proc = DedupProcessor(rdp_id=1)
    images = proc._collect_images()

    qs.values_list.assert_called_once_with("id", "flex_fields__photo")
    assert images == [{"reference_pk": "103", "filename": "photo.jpg"}]


def test_deduplicate_happy_path_updates_rdp_and_returns_uuid(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(
        pk=123,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    api = mocker.MagicMock()
    ds_id = uuid4()
    api.create_deduplication_set.return_value = str(ds_id)
    api.create_images.return_value = True
    api.process.return_value = True

    mocker.patch(
        f"{MOD}.dedup_api",
        return_value=mocker.MagicMock(
            __enter__=mocker.MagicMock(return_value=api),
            __exit__=mocker.MagicMock(return_value=False),
        ),
    )

    upd_qs = mocker.MagicMock()
    mocker.patch(f"{MOD}.Rdp.objects.filter", return_value=upd_qs)

    proc = DedupProcessor(rdp_id=rdp.pk)
    out = proc._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}])

    assert out == UUID(str(ds_id))
    upd_qs.update.assert_called_once_with(
        deduplication_set_id=UUID(str(ds_id)),
        dedup_run_state=Rdp.DedupRunState.IN_PROGRESS,
    )
    api.create_images.assert_called_once()
    api.process.assert_called_once_with()


def test_deduplicate_invalid_uuid_is_reported(
    mocker: MockerFixture, err_contains: Callable[[list[str], str], bool]
) -> None:
    rdp = mocker.MagicMock(
        pk=123,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    api = mocker.MagicMock()
    api.create_deduplication_set.return_value = "not-a-uuid"

    mocker.patch(
        f"{MOD}.dedup_api",
        return_value=mocker.MagicMock(
            __enter__=mocker.MagicMock(return_value=api),
            __exit__=mocker.MagicMock(return_value=False),
        ),
    )

    upd_qs = mocker.MagicMock()
    mocker.patch(f"{MOD}.Rdp.objects.filter", return_value=upd_qs)

    proc = DedupProcessor(rdp_id=rdp.pk)
    out = proc._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}])

    assert out is None
    assert err_contains(proc.total["errors"], "returned invalid UUID")
    upd_qs.update.assert_not_called()


def test_deduplicate_create_set_none(mocker: MockerFixture, dedup_processor, dedup_api_cm) -> None:
    api = mocker.MagicMock()
    api.create_deduplication_set.return_value = None

    mocker.patch(f"{MOD}.dedup_api", return_value=dedup_api_cm(api))
    spy_filter = mocker.patch(f"{MOD}.Rdp.objects.filter")

    assert dedup_processor._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}]) is None
    api.create_images.assert_not_called()
    api.process.assert_not_called()
    spy_filter.assert_not_called()
    assert dedup_processor.total["errors"] == []


@pytest.mark.parametrize(
    ("create_ok", "process_ok", "process_called"),
    [(False, True, False), (True, False, True)],
    ids=["create_images_false", "process_false"],
)
def test_deduplicate_create_images_or_process_fail(
    mocker: MockerFixture,
    dedup_processor,
    dedup_api_cm,
    create_ok: bool,
    process_ok: bool,
    process_called: bool,
) -> None:
    api = mocker.MagicMock()
    api.create_deduplication_set.return_value = uuid4()
    api.create_images.return_value = create_ok
    api.process.return_value = process_ok

    mocker.patch(f"{MOD}.dedup_api", return_value=dedup_api_cm(api))
    qs = mocker.MagicMock()
    mocker.patch(f"{MOD}.Rdp.objects.filter", return_value=qs)

    assert dedup_processor._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}]) is None
    qs.update.assert_called_once()
    assert dedup_processor.total["errors"] == []

    api.create_images.assert_called_once()
    if process_called:
        api.process.assert_called_once()
    else:
        api.process.assert_not_called()
