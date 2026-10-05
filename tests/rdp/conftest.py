from uuid import uuid4

import pytest

from country_workspace.models import Individual, Program, Rdp, RdpOperation
from country_workspace.rdp.push.types import PushWorkflowConfig


@pytest.fixture
def program() -> Program:
    from testutils.factories import ProgramFactory

    return ProgramFactory()


@pytest.fixture
def rdp(program: Program) -> Rdp:
    from testutils.factories import RdpFactory

    return RdpFactory(program=program)


@pytest.fixture
def biometric_operation(rdp: Rdp) -> RdpOperation:
    from testutils.factories import BiometricRdpOperationFactory

    return BiometricRdpOperationFactory(rdp=rdp)


@pytest.fixture
def successful_biometric_operation(rdp: Rdp) -> RdpOperation:
    from testutils.factories import BiometricRdpOperationFactory

    return BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)


@pytest.fixture
def running_biometric_operation(rdp: Rdp) -> RdpOperation:
    from testutils.factories import BiometricRdpOperationFactory

    return BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.RUNNING)


@pytest.fixture
def failed_biometric_operation(rdp: Rdp) -> RdpOperation:
    from testutils.factories import BiometricRdpOperationFactory

    return BiometricRdpOperationFactory(
        rdp=rdp,
        status=RdpOperation.Status.FAILURE,
        error={"message": "failed"},
    )


@pytest.fixture
def people_rdp(rdp: Rdp) -> tuple[Rdp, list[Individual]]:
    from testutils.factories import IndividualFactory

    rdp.program.beneficiary_group.master_detail = False
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])
    individuals = [IndividualFactory(household=None, batch__program=rdp.program) for _ in range(3)]
    rdp.individuals.set(individuals)
    return rdp, individuals


@pytest.fixture
def push_pending_rdp(rdp: Rdp) -> Rdp:
    rdp.status = Rdp.PushStatus.PUSH_PENDING
    rdp.push_attempt_id = uuid4()
    rdp.hope_rdi_id = None
    rdp.save(update_fields=["status", "push_attempt_id", "hope_rdi_id"])
    return rdp


@pytest.fixture
def push_config(rdp: Rdp) -> PushWorkflowConfig:
    return {
        "batch_name": rdp.name,
        "co_slug": rdp.program.country_office.slug,
        "country_workspace_id": f"rdp-{rdp.pk}",
        "imported_by_email": "user@example.com",
        "master_detail": False,
        "pks": [],
        "program_hope_id": rdp.program.hope_id,
        "rdp_id": rdp.pk,
    }


@pytest.fixture
def review_pending_rdp(rdp: Rdp) -> Rdp:
    rdp.status = Rdp.PushStatus.REVIEW_PENDING
    rdp.save(update_fields=["status"])
    return rdp


@pytest.fixture
def successful_rdp(rdp: Rdp) -> Rdp:
    rdp.status = Rdp.PushStatus.SUCCESS
    rdp.save(update_fields=["status"])
    return rdp
