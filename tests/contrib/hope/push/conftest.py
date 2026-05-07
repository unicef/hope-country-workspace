import pytest
from pytest_mock import MockerFixture
from collections.abc import Callable
from typing import Any
from hope_flex_fields.models import DataChecker

from country_workspace.contrib.hope.push.config import Beneficiary, ERROR_CONFIG
from country_workspace.contrib.hope.push import PushProcessor
from country_workspace.models import AsyncJob, Office, User
from country_workspace.state import state
from country_workspace.workspaces.models import CountryProgram, CountryRdp


@pytest.fixture
def office() -> Office:
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def only_master_detail(master_detail: bool) -> None:
    if not master_detail:
        pytest.skip("Not applicable for people-only mode")


@pytest.fixture
def only_people_only(master_detail: bool) -> None:
    if master_detail:
        pytest.skip("Not applicable for master-detail mode")


@pytest.fixture
def program(
    office: Office,
    master_detail: bool,
    force_migrated_records: bool,
    household_checker: DataChecker,
    individual_checker: DataChecker,
) -> CountryProgram:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group__master_detail=master_detail,
    )


@pytest.fixture
def rdp(program: CountryProgram) -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def beneficiary_instance(program: CountryProgram, rdp: CountryRdp) -> Beneficiary:
    """
    Beneficiary already linked to an existing RDP (used by push_existing_* / mark_removed tests).
    """
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(rdps=rdp)
    if not program.beneficiary_group.master_detail:
        ind = hh.members.first()
        ind.rdp.add(rdp)
        return ind
    return hh


@pytest.fixture
def create_beneficiary_instance(program: CountryProgram) -> Beneficiary:
    """
    Beneficiary NOT linked to any RDP (used by create_rdp_* tests).
    """
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory()
    hh.rdp.clear()

    if not program.beneficiary_group.master_detail:
        ind = hh.members.first() or CountryIndividualFactory(household=hh)
        ind.rdp.clear()
        return ind
    return hh


@pytest.fixture
def user() -> User:
    from testutils.factories import UserFactory

    return UserFactory()


@pytest.fixture
def push_config_base(beneficiary_instance: Beneficiary, user: User) -> dict[str, Any]:
    """
    Base workflow config used by processor/unit tests (derived from an existing RDP).
    """
    rdp = beneficiary_instance.rdp.first()
    return {
        "batch_name": f"Test Batch - {rdp.program.name}",
        "co_slug": rdp.program.country_office.slug,
        "country_office_id": rdp.program.country_office.id,
        "master_detail": rdp.program.beneficiary_group.master_detail,
        "pks": [beneficiary_instance.pk],
        "program_id": rdp.program.id,
        "program_hope_id": rdp.program.hope_id,
        "pushed_by_id": user.id,
        "imported_by_email": user.email,
    }


@pytest.fixture
def create_config_base(program: CountryProgram, create_beneficiary_instance: Beneficiary, user: User) -> dict[str, Any]:
    """
    Minimal CreateRdpConfig for create_rdp_records/create_rdp_core.
    """
    return {
        "batch_name": f"Test Batch - {program.name}",
        "country_office_id": program.country_office.id,
        "program_id": program.id,
        "pushed_by_id": user.id,
        "master_detail": program.beneficiary_group.master_detail,
        "pks": [create_beneficiary_instance.pk],
    }


@pytest.fixture
def create_job(program: CountryProgram, create_config_base: dict[str, Any]) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(program=program, config=create_config_base)


@pytest.fixture
def job(beneficiary_instance: Beneficiary, push_config_base: dict[str, Any]) -> AsyncJob:
    """
    Push job must include rdp_id because push_existing_rdp_core reads job.config['rdp_id'].
    """
    from testutils.factories import AsyncJobFactory

    rdp = beneficiary_instance.rdp.first()
    cfg = {**push_config_base, "rdp_id": rdp.id}
    return AsyncJobFactory(program=rdp.program, rdp=rdp, config=cfg)


@pytest.fixture
def processor(job: AsyncJob) -> PushProcessor:
    return PushProcessor(job.config)


@pytest.fixture
def qs() -> Callable[[list[Any]], Any]:
    """Fixture that returns a minimal queryset-like object with .iterator()."""

    class _QS:
        def __init__(self, items: list[Any]) -> None:
            self._items = items

        def iterator(self, chunk_size: int | None = None):
            yield from self._items

    def callback(items):
        return _QS(items)

    return callback


@pytest.fixture
def beneficiary_stub() -> Callable[..., Beneficiary]:
    """Factory fixture for a tiny attribute bag with a few helper methods."""

    class _Stub:
        def __init__(self, **kw: Any) -> None:
            if "id" not in kw and "pk" in kw:
                kw["id"] = kw["pk"]
            kw.setdefault("originating_id", kw.get("id"))
            self.__dict__.update(kw)

        def is_valid(self):
            return getattr(self, "_valid", True)

        def apply_grouping(self):
            return getattr(self, "_group", {})

    def callback(**kw):
        return _Stub(**kw)

    return callback


@pytest.fixture
def serializer_identity(processor: PushProcessor) -> PushProcessor:
    """Disable JSON serialization: pass rows through as-is for prepare_* tests."""
    processor.__dict__["serializer"] = lambda rows: rows
    return processor


@pytest.fixture
def errs() -> list[str]:
    return []


@pytest.fixture
def err(errs):
    return errs.append


@pytest.fixture
def err_contains() -> Callable[[list[str], str], bool]:
    def _contains(errors: list[str], expected: str) -> bool:
        ln = ERROR_CONFIG.MAX_ERROR_LEN
        truncated = expected if len(expected) <= ln else f"{expected[: ln - 1]}…"
        return any((expected in error) or (truncated in error) for error in errors)

    return _contains


@pytest.fixture
def dedup_api_cm(mocker: MockerFixture) -> Callable[[Any], Any]:
    def _cm(api: Any) -> Any:
        return mocker.MagicMock(
            __enter__=mocker.Mock(return_value=api),
            __exit__=mocker.Mock(return_value=False),
        )

    return _cm


@pytest.fixture
def dedup_processor(rdp: CountryRdp):
    from country_workspace.contrib.hope.push.processor import DedupProcessor

    return DedupProcessor(rdp)
