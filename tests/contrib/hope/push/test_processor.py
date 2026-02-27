import pytest
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.processor import DedupProcessor, PushProcessor
from country_workspace.contrib.hope.push.config import Beneficiary, ErrorConfig
from country_workspace.models import Rdp


# ----------------------------- serializer ------------------------------


@pytest.mark.django_db
def test_serializer_cached_once(mocker: MockerFixture, processor: PushProcessor) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    stub_ser = lambda rows: rows
    spy = mocker.patch(f"{mod}.serializer_for_program", return_value=stub_ser)

    assert processor.serializer is processor.serializer
    spy.assert_called_once_with(processor.program_hope_id)


# ------------------------------ preflight ------------------------------


@pytest.mark.django_db
def test_preflight_collects_preflight_errors(mocker: MockerFixture, processor: PushProcessor) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    processor.master_detail, processor.pks, processor.rdp_id = True, [1, 2], 10

    msgs = ["boom-1", "boom-2"]
    spy = mocker.patch(f"{mod}.preflight_errors", return_value=msgs)

    processor.preflight()

    spy.assert_called_once_with(pks=[1, 2], master_detail=True, exclude_rdp_id=10)
    assert processor.total["errors"] == msgs


@pytest.mark.django_db
def test_preflight_empty_pks_is_ok(mocker: MockerFixture, processor: PushProcessor) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    processor.master_detail, processor.pks, processor.rdp_id = False, [], None

    spy = mocker.patch(f"{mod}.preflight_errors", return_value=[])

    processor.preflight()

    spy.assert_called_once_with(pks=[], master_detail=False, exclude_rdp_id=None)
    assert processor.total["errors"] == []


# ------------------------------- RDI ops -------------------------------


@pytest.mark.django_db
def test_rdi_create_success_and_failure(
    mocker: MockerFixture, processor: PushProcessor, err_contains: Callable[[list[str], str], bool]
) -> None:
    mocker.patch.object(processor.api, "create_rdi", return_value={"id": "rdi-1"})
    processor.rdi_create()
    assert processor.hope_rdi_id == "rdi-1"

    processor.hope_rdi_id = None
    mocker.patch.object(processor.api, "create_rdi", return_value={"foo": "bar"})
    processor.rdi_create()
    assert err_contains(processor.total["errors"], "can't create")


@pytest.mark.parametrize(("rid", "called"), [(None, False), ("RID-1", True)], ids=["no_rdi", "has_rdi"])
def test_rdi_complete_paths(
    mocker: MockerFixture,
    processor: PushProcessor,
    rid: str | None,
    called: bool,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    processor.hope_rdi_id = rid
    spy = mocker.patch.object(processor.api, "complete_rdi")

    processor.rdi_complete()

    assert spy.called is called
    if not called:
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

    prepare = lambda batch: (list(batch), [{"n": i} for i in batch])
    post = mocker.Mock(return_value={"ok": True})
    proc = mocker.Mock()

    processor._push_batched("X", prepare, lambda rid, payload: post(rid, payload), proc)

    post.assert_called_once()
    assert [c.args[1] for c in proc.call_args_list] == [[1]]


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


# ---------------------------- prepare_* --------------------------------


@pytest.mark.django_db
def test_prepare_households_batch_uses_mapping_and_serializer(
    mocker: MockerFixture,
    processor: PushProcessor,
    serializer_identity: Callable,
    beneficiary_stub: Callable[..., Beneficiary],
) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    mocker.patch(f"{mod}.ROLE_FIELDS", ("head_of_household",))

    mocker.patch(
        f"{mod}.map_role_value",
        side_effect=lambda ind_map, _err, _hh_pk, _key, value: ind_map.get(value),
    )
    mocker.patch(
        f"{mod}.map_members",
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
        (None, [9], False),
    ],
    ids=["all_accepted", "unexpected_shape", "resp_none"],
)
def test_process_households_response_paths(
    processor: PushProcessor,
    resp: dict | None,
    ids: list[int],
    ok: bool,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    processor.total = {"errors": []}
    processor._process_households_response(resp, ids)

    if ok:
        assert processor.total.get("households") == 2
    else:
        assert any(err_contains(processor.total["errors"], s) for s in ("batch failed", "push error", "unexpected"))


@pytest.mark.django_db
def test_process_individuals_response_paths(
    mocker: MockerFixture, processor: PushProcessor, err_contains: Callable[[list[str], str], bool]
) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    processor.total = {"errors": []}
    mocker.patch(f"{mod}.load_mapping_from_api", return_value={1: "IND-1", 2: "IND-2"})

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
    processor._process_individuals_response(None, [1])
    assert err_contains(processor.total["errors"], "batch failed")

    processor.total["errors"].clear()
    processor._process_individuals_response({}, [1])
    assert err_contains(processor.total["errors"], "unexpected response")


@pytest.mark.django_db
def test_individuals_mapping_accumulates_across_batches(mocker: MockerFixture, processor: PushProcessor) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    mocker.patch(f"{mod}.load_mapping_from_api", side_effect=[{1: "IND-1"}, {2: "IND-2"}])
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
        (None, [1], False),
    ],
    ids=["ok_two_people", "unexpected_rdi", "resp_none"],
)
def test_process_people_response_paths(
    processor: PushProcessor,
    resp: dict | None,
    ids: list[int],
    ok: bool,
    err_contains: Callable[[list[str], str], bool],
) -> None:
    processor.total, processor.hope_rdi_id = {"errors": []}, "rdi-x"
    processor._process_people_response(resp, ids)

    if ok:
        assert processor.total.get("people") == 2
    else:
        assert any(err_contains(processor.total["errors"], s) for s in ("batch failed", "unexpected"))


@pytest.mark.parametrize(
    ("resp", "expected"),
    [(None, True), ({"errors": ["x"]}, True), ({"ok": True}, False)],
    ids=["none", "has_errors", "ok"],
)
def test_resp_err(processor: PushProcessor, resp: dict | None, expected: bool) -> None:
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
    cfg = ErrorConfig(MAX_ERRORS=3, MAX_ERROR_LEN=10, MARKER="⟪TRUNC⟫")
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


# ------------------------------ dedup ----------------------------------


def test_dedup_run_rejects_non_pending(mocker: MockerFixture, err_contains: Callable[[list[str], str], bool]) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.SUCCESS,
        dedup_run_state=None,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

    proc = DedupProcessor(rdp_id=1)
    proc.run()

    assert err_contains(proc.total["errors"], "can not run dedup in status")
    assert "rdp_id" not in proc.total


def test_dedup_run_rejects_after_finished(
    mocker: MockerFixture, err_contains: Callable[[list[str], str], bool]
) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=Rdp.DedupRunState.FINISHED,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

    proc = DedupProcessor(rdp_id=1)
    proc.run()

    assert err_contains(proc.total["errors"], "already finished")
    assert "rdp_id" not in proc.total


def test_dedup_run_no_images_sets_none(mocker: MockerFixture) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

    proc = DedupProcessor(rdp_id=1)
    mocker.patch.object(proc, "_collect_images", return_value=[])
    spy = mocker.patch.object(proc, "_deduplicate")

    proc.run()

    spy.assert_not_called()
    assert proc.total["errors"] == []
    assert proc.total["rdp_id"] == 1
    assert proc.total["program"] == "CO-PRG"
    assert proc.total["images_sent"] == 0
    assert proc.total["deduplication_set_id"] is None


def test_dedup_run_success_sets_uuid(mocker: MockerFixture) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

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
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=1,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

    class _Rows:
        def __init__(self, pairs):
            self._pairs = pairs

        def iterator(self, chunk_size=None):
            yield from self._pairs

    class _QS:
        def __init__(self, pairs):
            self._pairs = pairs

        def values_list(self, *args, **kwargs):
            return _Rows(self._pairs)

    pairs = [
        (100, None),
        (101, ""),
        (102, "   "),
        (103, " photo.jpg "),
    ]
    mocker.patch(f"{mod}.individuals_for_rdp", return_value=_QS(pairs))

    proc = DedupProcessor(rdp_id=1)
    images = proc._collect_images()

    assert images == [{"reference_pk": "103", "filename": "photo.jpg"}]


def test_deduplicate_happy_path_updates_rdp_and_returns_uuid(mocker: MockerFixture) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=123,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

    api = mocker.MagicMock()
    ds_id = uuid4()
    api.create_deduplication_set.return_value = str(ds_id)
    api.create_images.return_value = True
    api.process.return_value = True

    mocker.patch(
        f"{mod}.dedup_api",
        return_value=mocker.MagicMock(
            __enter__=mocker.Mock(return_value=api),
            __exit__=mocker.Mock(return_value=False),
        ),
    )

    upd_qs = mocker.MagicMock()
    mocker.patch(f"{mod}.Rdp.objects.filter", return_value=upd_qs)

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
    mod = "country_workspace.contrib.hope.push.processor"
    rdp = mocker.MagicMock(
        pk=123,
        program=mocker.MagicMock(unicef_id="CO-PRG"),
        status=Rdp.PushStatus.PENDING,
        dedup_run_state=None,
    )
    mocker.patch(f"{mod}.rdp_for_dedup", return_value=rdp)

    api = mocker.MagicMock()
    api.create_deduplication_set.return_value = "not-a-uuid"

    mocker.patch(
        f"{mod}.dedup_api",
        return_value=mocker.MagicMock(
            __enter__=mocker.Mock(return_value=api),
            __exit__=mocker.Mock(return_value=False),
        ),
    )

    upd_qs = mocker.MagicMock()
    mocker.patch(f"{mod}.Rdp.objects.filter", return_value=upd_qs)

    proc = DedupProcessor(rdp_id=rdp.pk)
    out = proc._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}])

    assert out is None
    assert err_contains(proc.total["errors"], "returned invalid UUID")
    upd_qs.update.assert_not_called()


def test_deduplicate_create_set_none(mocker, dedup_processor, dedup_api_cm, err_contains) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    api = mocker.MagicMock()
    api.create_deduplication_set.return_value = None

    mocker.patch(f"{mod}.dedup_api", return_value=dedup_api_cm(api))
    spy_filter = mocker.patch(f"{mod}.Rdp.objects.filter")

    assert dedup_processor._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}]) is None
    api.create_images.assert_not_called()
    api.process.assert_not_called()
    spy_filter.assert_not_called()
    assert err_contains(dedup_processor.total["errors"], "create_deduplication_set")


@pytest.mark.parametrize(
    ("create_ok", "process_ok", "process_called", "expected"),
    [(False, True, False, "create_images"), (True, False, True, "process")],
    ids=["create_images_false", "process_false"],
)
def test_deduplicate_create_images_or_process_fail(
    mocker,
    dedup_processor,
    dedup_api_cm,
    err_contains,
    create_ok: bool,
    process_ok: bool,
    process_called: bool,
    expected: str,
) -> None:
    mod = "country_workspace.contrib.hope.push.processor"
    api = mocker.MagicMock()
    api.create_deduplication_set.return_value = uuid4()
    api.create_images.return_value = create_ok
    api.process.return_value = process_ok

    mocker.patch(f"{mod}.dedup_api", return_value=dedup_api_cm(api))
    qs = mocker.MagicMock()
    mocker.patch(f"{mod}.Rdp.objects.filter", return_value=qs)

    assert dedup_processor._deduplicate([{"reference_pk": "1", "filename": "a.jpg"}]) is None
    qs.update.assert_called_once()
    assert err_contains(dedup_processor.total["errors"], expected)

    api.create_images.assert_called_once()
    (api.process.assert_called_once() if process_called else api.process.assert_not_called())
