from uuid import uuid4

import pytest

from hope_flex_fields.registry import field_registry

from country_workspace.models import Individual, Program, Rdp, RdpOperation
from country_workspace.rdp.push.types import PushWorkflowConfig
from country_workspace.utils.flex_fields import Base64ImageField

PHOTO_DATA_URI = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
def photo_individuals(people_rdp: tuple[Rdp, list[Individual]]) -> list[Individual]:
    from testutils.factories import (
        DataCheckerFieldsetFactory,
        FieldDefinitionFactory,
        FieldsetFactory,
        FlexFieldFactory,
    )

    rdp, individuals = people_rdp
    field_registry.register(Base64ImageField)
    fieldset = FieldsetFactory()
    FlexFieldFactory(
        fieldset=fieldset,
        name="photo",
        definition=FieldDefinitionFactory(field_type=Base64ImageField),
    )
    DataCheckerFieldsetFactory(checker=rdp.program.individual_checker, fieldset=fieldset, prefix="")
    for individual, photo in zip(individuals, (PHOTO_DATA_URI, "", None), strict=True):
        individual.flex_fields = {"photo": photo}
        individual.save(update_fields=["flex_fields"])
    return individuals


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
