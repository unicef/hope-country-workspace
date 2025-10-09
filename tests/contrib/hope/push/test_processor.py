import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.processor import PushProcessor


# ----------------------------- serializer ------------------------------


@pytest.mark.django_db
def test_serializer_cached_once(mocker: MockerFixture, processor: PushProcessor):
    mod = "country_workspace.contrib.hope.push.processor"
    stub_ser = lambda rows: rows
    spy = mocker.patch(f"{mod}.serializer_for_program", return_value=stub_ser)

    # property should memoize; underlying factory called once
    assert processor.serializer is processor.serializer
    spy.assert_called_once_with(processor.program_hope_id)


# ------------------------------ preflight ------------------------------


@pytest.mark.django_db
def test_preflight_master_detail_logs(mocker: MockerFixture, processor: PushProcessor, qs, beneficiary_stub):
    mod = "country_workspace.contrib.hope.push.processor"
    processor.master_detail, processor.pks, processor.rdp_id = True, [1, 2], 10
    mocker.patch(f"{mod}.rdp_pending_or_success", return_value="rdp_qs")

    hh1 = beneficiary_stub(pk=101, _valid=False)
    hh2 = beneficiary_stub(pk=102, _valid=True, rdp_pre=[7])
    ind = beneficiary_stub(pk=201, _valid=False)

    mocker.patch(f"{mod}.households_for_preflight", return_value=qs([hh1, hh2]))
    mocker.patch(f"{mod}.individuals_for_preflight_by_households", return_value=qs([ind]))

    processor.preflight()
    msg = "".join(processor.total.get("errors", []))
    assert f"HH #{hh1.pk} invalid" in msg
    assert f"HH #{hh2.pk} already in another RDP" in msg
    assert f"Ind #{ind.pk} invalid" in msg


@pytest.mark.django_db
def test_preflight_non_master_detail_logs(mocker: MockerFixture, processor: PushProcessor, qs, beneficiary_stub):
    mod = "country_workspace.contrib.hope.push.processor"
    processor.master_detail, processor.pks, processor.rdp_id = False, [5], 11
    mocker.patch(f"{mod}.rdp_pending_or_success", return_value="rdp_qs")

    ind1 = beneficiary_stub(pk=301, _valid=True, rdp_pre=[2])
    ind2 = beneficiary_stub(pk=302, _valid=False)
    mocker.patch(f"{mod}.individuals_for_preflight_by_pks", return_value=qs([ind1, ind2]))

    processor.preflight()
    msg = "".join(processor.total.get("errors", []))
    assert f"Ind #{ind1.pk} already in another RDP" in msg
    assert f"Ind #{ind2.pk} invalid" in msg


@pytest.mark.django_db
def test_preflight_returns_early_when_no_pks(mocker: MockerFixture, processor: PushProcessor):
    mod = "country_workspace.contrib.hope.push.processor"
    processor.pks = []
    spy_rdp = mocker.patch(f"{mod}.rdp_pending_or_success")
    spy_hh = mocker.patch(f"{mod}.households_for_preflight")
    spy_ind = mocker.patch(f"{mod}.individuals_for_preflight_by_pks")

    processor.preflight()

    assert not spy_rdp.called
    assert not spy_hh.called
    assert not spy_ind.called
    assert processor.total["errors"] == []


# ------------------------------- RDI ops -------------------------------


@pytest.mark.django_db
def test_rdi_create_success_and_failure(mocker: MockerFixture, processor: PushProcessor):
    mocker.patch.object(processor.api, "create_rdi", return_value={"id": "rdi-1"})
    processor.rdi_create()
    assert processor.hope_rdi_id == "rdi-1"

    processor.hope_rdi_id = None
    mocker.patch.object(processor.api, "create_rdi", return_value={"foo": "bar"})
    processor.rdi_create()
    assert any("cannot create" in e for e in processor.total["errors"])


@pytest.mark.parametrize(("rid", "called"), [(None, False), ("RID-1", True)], ids=["no_rdi", "has_rdi"])
def test_rdi_complete_paths(mocker: MockerFixture, processor: PushProcessor, rid, called):
    processor.hope_rdi_id = rid
    spy = mocker.patch.object(processor.api, "complete_rdi")
    processor.rdi_complete()
    assert spy.called is called
    if not called:
        assert any("cannot complete" in e for e in processor.total["errors"])


# ------------------------- rdi_push_* delegate -------------------------


@pytest.mark.parametrize(
    ("method", "label"),
    [("rdi_push_households", "Households"), ("rdi_push_individuals", "Individuals"), ("rdi_push_people", "People")],
    ids=["households", "individuals", "people"],
)
def test_rdi_push_methods_delegate(mocker: MockerFixture, processor: PushProcessor, method, label):
    spy = mocker.patch.object(processor, "_push_batched")
    getattr(processor, method)()
    spy.assert_called_once()
    assert spy.call_args.args[0] == label


# ----------------------------- batching --------------------------------


def test_push_batched_happy_path(mocker: MockerFixture, processor: PushProcessor, qs):
    processor.hope_rdi_id = "rdi"
    processor.queryset = qs([1])

    prepare = lambda batch: (list(batch), [{"n": i} for i in batch])
    post = mocker.Mock(return_value={"ok": True})
    proc = mocker.Mock()

    processor._push_batched("X", prepare, lambda rid, payload: post(rid, payload), proc)
    post.assert_called_once()
    assert [c.args[1] for c in proc.call_args_list] == [[1]]


def test_push_batched_requires_context(processor: PushProcessor):
    processor.total = {"errors": []}
    processor.queryset = None
    processor.hope_rdi_id = None

    processor._push_batched("X", lambda _: ([], []), lambda *_: {}, lambda *_: None)
    assert any("hope_rdi_id is not set" in e for e in processor.total["errors"])

    processor.hope_rdi_id = "rdi"
    processor._push_batched("X", lambda _: ([], []), lambda *_: {}, lambda *_: None)
    assert any("queryset is not set" in e for e in processor.total["errors"])


# ---------------------------- prepare_* --------------------------------


@pytest.mark.django_db
def test_prepare_households_batch_uses_mapping_and_serializer(
    mocker: MockerFixture, processor: PushProcessor, serializer_identity, beneficiary_stub
):
    members = [beneficiary_stub(id=1), beneficiary_stub(id=2)]
    hh = beneficiary_stub(pk=777, prefetched_members=members)
    hh._group = {"head_of_household": members[0].id, "keep": "x", "drop": None}

    # mapping for all members
    processor.ind_id_map = {m.id: f"IND-{m.id}.X" for m in members}

    ids, payload = processor._prepare_households_batch([hh])
    assert ids == [hh.pk]
    assert payload == [
        {
            "head_of_household": "IND-1.X",
            "members": ["IND-1.X", "IND-2.X"],
            "keep": "x",
        }
    ]


def test_prepare_individuals_batch_injects_id(processor: PushProcessor, serializer_identity, beneficiary_stub):
    i1, i2 = beneficiary_stub(id=10, _group={"a": 1}), beneficiary_stub(id=11, _group={"b": 2})

    ids, rows = processor._prepare_individuals_batch([i1, i2])
    assert ids == [10, 11]
    assert {"a": 1, "individual_id": 10} in rows
    assert {"b": 2, "individual_id": 11} in rows


def test_prepare_people_batch_plain(processor: PushProcessor, serializer_identity, beneficiary_stub):
    i1, i2 = beneficiary_stub(id=10, _group={"a": 1}), beneficiary_stub(id=11, _group={"b": 2})
    ids, rows = processor._prepare_people_batch([i1, i2])
    assert ids == [10, 11]
    assert rows == [{"a": 1}, {"b": 2}]


# ------------------------- response handlers ---------------------------


@pytest.mark.parametrize(
    ("resp", "ids", "ok"),
    [
        ({"processed": 2, "accepted": 2}, [1, 2], True),
        ({"processed": 1, "accepted": 0}, [9], False),
        (None, [9], False),
    ],
    ids=["all_accepted", "accepted_zero", "resp_none"],
)
def test_process_households_response_paths(processor: PushProcessor, resp, ids, ok):
    processor.total = {"errors": []}
    processor._process_households_response(resp, ids)
    if ok:
        assert processor.total.get("households") == 2
    else:
        assert any("batch failed" in e or "mismatch" in e or "unexpected" in e for e in processor.total["errors"])


@pytest.mark.django_db
def test_process_individuals_response_paths(mocker: MockerFixture, processor: PushProcessor):
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
    assert any("accepted mismatch" in e for e in processor.total["errors"])
    assert processor.total.get("individuals") == 3

    processor.total["errors"].clear()
    processor._process_individuals_response(None, [1])
    assert any("batch failed" in e for e in processor.total["errors"])

    processor.total["errors"].clear()
    processor._process_individuals_response({}, [1])
    assert any("unexpected response" in e for e in processor.total["errors"])


@pytest.mark.django_db
def test_individuals_mapping_accumulates_across_batches(mocker: MockerFixture, processor: PushProcessor):
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
    assert not any("unexpected" in e or "batch failed" in e for e in processor.total["errors"])


@pytest.mark.parametrize(
    ("resp", "ids", "ok"),
    [
        ({"id": "rdi-x", "people": [{}, {}]}, [1, 2], True),
        ({"id": "rdi-y", "people": [{}]}, [1], False),
        (None, [1], False),
    ],
    ids=["ok_two_people", "unexpected_rdi", "resp_none"],
)
def test_process_people_response_paths(processor: PushProcessor, resp, ids, ok):
    processor.total, processor.hope_rdi_id = {"errors": []}, "rdi-x"
    processor._process_people_response(resp, ids)
    if ok:
        assert processor.total.get("people") == 2
    else:
        assert any("batch failed" in e or "unexpected" in e for e in processor.total["errors"])


@pytest.mark.parametrize(
    ("resp", "expected"),
    [(None, True), ({"errors": ["x"]}, True), ({"ok": True}, False)],
    ids=["none", "has_errors", "ok"],
)
def test_resp_err(processor: PushProcessor, resp, expected):
    processor.total = {"errors": []}
    assert processor._resp_err("T", resp, [1]) is expected


# ------------------------------- queryset ------------------------------


def test_using_qs_sets_and_restores(processor: PushProcessor, qs):
    q = qs([1])
    assert processor.queryset is None
    with processor._using_qs(q):
        assert processor.queryset is q
    assert processor.queryset is None


def test_run_with_sets_qs_and_invokes_step(processor: PushProcessor, qs):
    q = qs([1])
    called = []

    def step():
        assert processor.queryset is q
        called.append(True)

    processor.run_with(q, step)
    assert called == [True]
    assert processor.queryset is None
