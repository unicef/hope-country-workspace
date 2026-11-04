import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture, MockType

from country_workspace.models import Program, Rdp, User
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import creation
from country_workspace.rdp.types import CreateRdpConfig


pytestmark = pytest.mark.django_db


@pytest.fixture
def creation_config(program: Program, user: User) -> CreateRdpConfig:
    return {
        "batch_name": "Test RDP",
        "country_office_id": program.country_office_id,
        "program_id": program.pk,
        "pushed_by_id": user.pk,
        "master_detail": False,
        "pks": [1],
        "operations": [],
    }


@pytest.fixture
def creation_job(program: Program, creation_config: CreateRdpConfig, mocker: MockerFixture) -> MockType:
    return mocker.MagicMock(id=10, program=program, config=creation_config)


@pytest.mark.parametrize("errors", [[], ["invalid"]], ids=["valid", "invalid"])
def test_validate_rdp_creation(
    program: Program, creation_config: CreateRdpConfig, mocker: MockerFixture, errors: list[str]
) -> None:
    preflight = mocker.patch.object(creation, "preflight_errors", return_value=errors)

    if errors:
        with pytest.raises(RdpWorkflowError) as exc:
            creation.validate_rdp_creation(program=program, config=creation_config)
        assert "invalid" in str(exc.value)
    else:
        creation.validate_rdp_creation(program=program, config=creation_config)

    preflight.assert_called_once_with(pks=[1], master_detail=False, exclude_rdp_ids=())


def test_validate_rdp_creation_requires_beneficiary_group(program: Program, creation_config: CreateRdpConfig) -> None:
    program.beneficiary_group = None

    with pytest.raises(RdpWorkflowError, match="beneficiary_group"):
        creation.validate_rdp_creation(program=program, config=creation_config)


def test_create_rdp_core(creation_job: MockType, mocker: MockerFixture) -> None:
    mocker.patch.object(creation, "validate_rdp_creation")
    created = mocker.MagicMock(id=123)
    mocker.patch.object(creation, "create_rdp", return_value=created)
    update = mocker.patch.object(creation.AsyncJob.objects, "filter")
    schedule = mocker.patch.object(creation, "schedule_rdp_processing")

    assert creation.create_rdp_core(creation_job) == {"rdp_id": 123}

    update.assert_called_once_with(id=creation_job.id)
    update.return_value.update.assert_called_once_with(rdp=created)
    schedule.assert_called_once_with(rdp=created)


def test_create_rdp_core_during_program_cleanup(creation_job: MockType, mocker: MockerFixture) -> None:
    Program.objects.filter(pk=creation_job.program.pk).update(cleanup_in_progress=True)
    mocker.patch.object(creation, "validate_rdp_creation")
    create = mocker.patch.object(creation, "create_rdp")
    schedule = mocker.patch.object(creation, "schedule_rdp_processing")

    with pytest.raises(RdpWorkflowError, match="cleanup"):
        creation.create_rdp_core(creation_job)

    create.assert_not_called()
    schedule.assert_not_called()


@pytest.mark.parametrize(
    ("message", "expected"),
    [("uniq_non_terminal_rdp_per_program", "unfinished"), ("other constraint", "create record")],
)
def test_create_rdp_core_converts_integrity_error(
    creation_job: MockType, mocker: MockerFixture, message: str, expected: str
) -> None:
    mocker.patch.object(creation, "validate_rdp_creation")
    mocker.patch.object(creation, "create_rdp", side_effect=IntegrityError(message))

    with pytest.raises(RdpWorkflowError, match=expected):
        creation.create_rdp_core(creation_job)


@pytest.mark.parametrize("with_operation", [True, False])
def test_schedule_rdp_processing(rdp: Rdp, mocker: MockerFixture, with_operation: bool) -> None:
    from testutils.factories import BiometricRdpOperationFactory

    if with_operation:
        BiometricRdpOperationFactory(rdp=rdp)

    operations = mocker.patch.object(creation, "schedule_rdp_operations")
    push = mocker.patch.object(creation, "schedule_rdp_push_evaluation")

    creation.schedule_rdp_processing(rdp=rdp)

    assert operations.called is with_operation
    assert push.called is not with_operation
