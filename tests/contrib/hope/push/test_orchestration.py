import pytest
from pytest_mock import MockerFixture
from collections.abc import Callable

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.models import Rdp, AsyncJob
from country_workspace.workspaces.models import CountryHousehold
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.orchestration import (
    create_rdp_core,
    create_rdp_records,
    dedup_existing_rdp_core,
    push_existing_rdp_core,
    mark_rdp_beneficiaries_removed,
    steps,
)
from country_workspace.contrib.hope.push import repository


MOD = "country_workspace.contrib.hope.push.orchestration"


@pytest.fixture
def proc() -> object:
    class P:
        def __init__(self):
            self.calls = []

        def preflight(self):
            self.calls.append("pre")

        def rdi_create(self):
            self.calls.append("create")

        def rdi_complete(self):
            self.calls.append("complete")

        def rdi_push_individuals(self):
            self.calls.append("push_inds")

        def rdi_push_households(self):
            self.calls.append("push_hhs")

        def rdi_push_people(self):
            self.calls.append("push_people")

        def run_with(self, qs, step):
            self.calls.append(("run_with", qs, step))

    return P()


@pytest.mark.django_db
def test_create_rdp_records_updates_async_job(create_config_base: dict, create_job: AsyncJob) -> None:
    rdp = create_rdp_records(create_config_base, create_job.id)
    create_job.refresh_from_db()
    assert create_job.rdp_id == rdp.id
    assert Rdp.objects.get(id=rdp.id).status == Rdp.PushStatus.PENDING


@pytest.mark.django_db
def test_create_rdp_records_integrity_error(job, push_config_base, err_contains) -> None:
    with pytest.raises(HopePushError) as exc:
        create_rdp_records(push_config_base, job.id)
    assert err_contains(exc.value.args[0].get("errors", []), "RDP: can not create record")


@pytest.mark.django_db
def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    md = job.program.beneficiary_group.master_detail
    mark_rdp_beneficiaries_removed(job.rdp, md)

    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.removed

    if md and isinstance(beneficiary_instance, CountryHousehold):
        for member in beneficiary_instance.members.all():
            member.refresh_from_db()
            assert member.removed


@pytest.mark.parametrize(
    ("beneficiary_group", "pks", "expected"),
    [
        (None, [1], "beneficiary_group is not set"),
        (object(), [], "no beneficiaries selected"),
    ],
    ids=["no_beneficiary_group", "no_pks"],
)
def test_create_rdp_core_guard_errors(
    mocker: MockerFixture,
    err_contains: Callable[[list[str], str], bool],
    beneficiary_group: object | None,
    pks: list[int],
    expected: str,
) -> None:
    job = mocker.MagicMock(
        program=mocker.MagicMock(
            beneficiary_group=beneficiary_group,
            biometric_deduplication_enabled=False,
        ),
        config={"pks": pks, "master_detail": True},
    )

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(job)

    assert err_contains(exc.value.args[0].get("errors", []), expected)


@pytest.mark.django_db
def test_create_rdp_core_preflight_errors(mocker: MockerFixture, create_job: AsyncJob) -> None:
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])
    spy_create = mocker.patch(f"{MOD}.create_rdp_records")

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert exc.value.args[0]["errors"] == ["boom"]
    spy_create.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("not_exposed", None),
        ("status_none", {"errors": []}),
        ("exists", {"errors": ["DedupEngine: there is an existing non-inactive deduplication set for this program."]}),
    ],
    ids=["not_exposed", "status_none", "exists"],
)
def test_create_rdp_core_dedup_guard(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
    case: str,
    expected: dict | None,
) -> None:
    create_job.program.biometric_deduplication_enabled = True

    spy_preflight = mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    fake_rdp = mocker.MagicMock(id=123)
    fake_rdp.__str__.return_value = "rdp"
    spy_create = mocker.patch(f"{MOD}.create_rdp_records", return_value=fake_rdp)

    de = mocker.MagicMock()
    sentinel = object()
    de.DEDUPLICATION_SET_NOT_EXPOSED = sentinel
    de.status.return_value = {
        "not_exposed": sentinel,
        "status_none": None,
        "exists": object(),
    }[case]

    mock_dedup_api = mocker.patch(f"{MOD}.dedup_api", return_value=dedup_api_cm(de))

    if expected is None:
        assert create_rdp_core(create_job) == {"rdp_id": 123, "rdp_str": "rdp"}
        spy_preflight.assert_called_once()
        spy_create.assert_called_once()
    else:
        with pytest.raises(HopePushError) as exc:
            create_rdp_core(create_job)
        assert exc.value.args[0] == expected
        spy_preflight.assert_not_called()
        spy_create.assert_not_called()

    mock_dedup_api.assert_called_once_with(create_job.program.unicef_id)
    de.status.assert_called_once_with()


@pytest.mark.django_db
def test_create_rdp_core_success(mocker: MockerFixture, create_job: AsyncJob) -> None:
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    out = create_rdp_core(create_job)

    create_job.refresh_from_db()
    assert out["rdp_id"] == create_job.rdp_id
    assert out["rdp_str"] == str(create_job.rdp)


@pytest.mark.parametrize(
    ("has_errors", "total"),
    [
        (False, {"errors": []}),
        (True, {"errors": ["boom"]}),
    ],
    ids=["success", "failure"],
)
def test_dedup_existing_rdp_core_paths(
    mocker: MockerFixture,
    has_errors: bool,
    total: dict[str, list[str]],
) -> None:
    job = mocker.MagicMock(config={"rdp_id": 123})
    proc = mocker.MagicMock(total=total, has_errors=has_errors)

    spy_cls = mocker.patch(f"{MOD}.DedupProcessor", return_value=proc)

    if has_errors:
        with pytest.raises(HopePushError) as exc:
            dedup_existing_rdp_core(job)
        assert exc.value.args[0] == total
    else:
        assert dedup_existing_rdp_core(job) == total

    spy_cls.assert_called_once_with(rdp_id=123)
    proc.run.assert_called_once_with()


@pytest.mark.django_db
@pytest.mark.parametrize("is_duplicate", [False, True], ids=["no_deduplicate", "duplicate"])
def test_push_existing_rdp_core_success(
    mocker: MockerFixture,
    job: AsyncJob,
    is_duplicate: bool,
) -> None:
    hope_rdi_id = "rdi-1"
    job.rdp.program.__class__.objects.filter(pk=job.rdp.program_id).update(
        biometric_deduplication_enabled=is_duplicate,
        code="TEST" if is_duplicate else job.rdp.program.code,
    )

    cfg = {
        "pks": [1],
        "master_detail": job.program.beneficiary_group.master_detail,
        "program_hope_id": "program-hope-id",
        "co_slug": "co",
        "batch_name": "Test Batch",
        "imported_by_email": "u@example.com",
    }
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=cfg)

    proc = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id=hope_rdi_id)
    mocker.patch(f"{MOD}.PushProcessor", return_value=proc)
    mocker.patch(f"{MOD}.steps", return_value=iter((lambda: None,)))

    mock_set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    mock_mark = mocker.patch(f"{MOD}.mark_rdp_beneficiaries_removed")
    mock_mark_dedup = mocker.patch(f"{MOD}.mark_rdp_dedup_finished", wraps=repository.mark_rdp_dedup_finished)

    push_existing_rdp_core(job)

    mock_set_status.assert_called_once()
    assert mock_set_status.call_args.kwargs["status"] == Rdp.PushStatus.SUCCESS
    assert mock_set_status.call_args.kwargs["hope_rdi_id"] == hope_rdi_id
    mock_mark.assert_called_once()

    if is_duplicate:
        mock_mark_dedup.assert_called_once_with(rdp_id=job.rdp.pk)
        job.rdp.refresh_from_db()
        assert job.rdp.dedup_run_state == Rdp.DedupRunState.FINISHED
    else:
        mock_mark_dedup.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "is_duplicate",
    [False, True],
    ids=["no_deduplicate", "duplicate"],
)
def test_push_existing_rdp_core_failure(mocker: MockerFixture, job: AsyncJob, is_duplicate: bool) -> None:
    hope_rdi_id = "test-rdi-123"
    job.config["rdp_id"] = job.rdp.id

    job.rdp.program.__class__.objects.filter(pk=job.rdp.program_id).update(
        biometric_deduplication_enabled=is_duplicate,
        code="TEST" if is_duplicate else job.rdp.program.code,
    )

    cfg = {
        "batch_name": "Test Batch",
        "co_slug": "co",
        "imported_by_email": "u@example.com",
        "program_hope_id": "program-hope-id",
        "master_detail": job.program.beneficiary_group.master_detail,
        "pks": [1],
    }
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=cfg)

    proc = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id=hope_rdi_id)
    mocker.patch(f"{MOD}.PushProcessor", return_value=proc)

    mock_set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    mock_mark = mocker.patch(f"{MOD}.mark_rdp_beneficiaries_removed")
    mock_mark_dedup = mocker.patch(f"{MOD}.mark_rdp_dedup_finished", wraps=repository.mark_rdp_dedup_finished)

    def _fail_step() -> None:
        proc.total["errors"].append("boom")
        proc.has_errors = True

    mocker.patch(f"{MOD}.steps", return_value=iter((_fail_step,)))

    with pytest.raises(HopePushError):
        push_existing_rdp_core(job)

    mock_set_status.assert_called_once()
    assert mock_set_status.call_args.kwargs["status"] == Rdp.PushStatus.FAILURE
    assert mock_set_status.call_args.kwargs["hope_rdi_id"] == hope_rdi_id
    mock_mark.assert_not_called()
    mock_mark_dedup.assert_not_called()


@pytest.mark.parametrize("master_detail", [True, False], ids=["md", "people_only"])
def test_steps_sequence(mocker: MockerFixture, proc, master_detail: bool) -> None:
    pks = [1, 2]
    cfg = {"pks": pks, "master_detail": master_detail}

    if master_detail:
        inds_qs, hhs_qs = object(), object()
        spy_inds = mocker.patch(f"{MOD}.individuals_by_household_pks", return_value=inds_qs)
        spy_hhs = mocker.patch(f"{MOD}.households", return_value=hhs_qs)

        expected_calls = [
            "pre",
            "create",
            ("run_with", inds_qs, proc.rdi_push_individuals),
            ("run_with", hhs_qs, proc.rdi_push_households),
            "complete",
        ]
    else:
        inds_qs = object()
        spy_inds = mocker.patch(f"{MOD}.individuals_by_pks", return_value=inds_qs)

        expected_calls = [
            "pre",
            "create",
            ("run_with", inds_qs, proc.rdi_push_people),
            "complete",
        ]

    for step in steps(proc, cfg):
        step()

    assert proc.calls == expected_calls
    spy_inds.assert_called_once_with(pks)
    if master_detail:
        spy_hhs.assert_called_once_with(pks=pks)
