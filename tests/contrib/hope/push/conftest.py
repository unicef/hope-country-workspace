import pytest
from hope_flex_fields.models import DataChecker

from country_workspace.models import Office, User, AsyncJob
from country_workspace.workspaces.models import (
    CountryProgram,
    CountryRdp,
)
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.processor import PushProcessor

from country_workspace.state import state


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request: pytest.FixtureRequest) -> bool:
    return request.param


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
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(rdps=rdp)
    if not program.beneficiary_group.master_detail:
        ind = hh.members.first()
        ind.rdp.add(rdp)
        return ind
    return hh


@pytest.fixture
def user() -> User:
    from testutils.factories import UserFactory

    return UserFactory()


# Config for push (without rdp_id for orchestration.create_rdp_records)
@pytest.fixture
def push_config_base(beneficiary_instance: Beneficiary, user: User) -> dict:
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


# Async job uses config without rdp_id (orchestration adds it)
@pytest.fixture
def job(beneficiary_instance: Beneficiary, push_config_base: dict) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    rdp = beneficiary_instance.rdp.first()
    return AsyncJobFactory(program=rdp.program, rdp=rdp, config=push_config_base)


# Processor constructed with WorkflowConfig (includes rdp_id)
@pytest.fixture
def processor(job: AsyncJob) -> PushProcessor:
    cfg = {**job.config, "rdp_id": job.rdp.id}
    return PushProcessor(cfg)


@pytest.fixture
def qs():
    """Fixture that returns a minimal queryset-like object with .iterator()."""

    class _QS:
        def __init__(self, items):
            self._items = items

        def iterator(self, chunk_size=None):
            yield from self._items

    return lambda items: _QS(items)


@pytest.fixture
def beneficiary_stub():
    """Factory fixture for a tiny attribute bag with a few helper methods.
    Mirrors pk -> id if only pk is provided.
    """

    class _Stub:
        def __init__(self, **kw):
            if "id" not in kw and "pk" in kw:
                kw["id"] = kw["pk"]
            self.__dict__.update(kw)

        def is_valid(self):
            return getattr(self, "_valid", True)

        def apply_grouping(self):
            return getattr(self, "_group", {})

    return lambda **kw: _Stub(**kw)


@pytest.fixture
def serializer_identity(processor: PushProcessor):
    """Disable JSON serialization: pass rows through as-is for prepare_* tests."""
    processor.__dict__["serializer"] = lambda rows: rows
    return processor


@pytest.fixture
def errs():
    return []


@pytest.fixture
def err(errs):
    return lambda msg: errs.append(msg)
