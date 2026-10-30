from typing import Any

from django.db import IntegrityError, transaction

from country_workspace.models import AsyncJob, Program, Rdp
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.workflow import schedule_rdp_operations
from country_workspace.rdp.push.workflow import schedule_rdp_push_evaluation
from country_workspace.rdp.repository import create_rdp
from country_workspace.rdp.types import CreateRdpConfig
from country_workspace.rdp.validation import preflight_errors


def validate_rdp_creation(
    *,
    program: Program,
    config: CreateRdpConfig,
    exclude_rdp_ids: tuple[int, ...] = (),
) -> None:
    """Validate a selection before creating an RDP."""
    if program.beneficiary_group is None:
        raise RdpWorkflowError({"errors": ["RDP: beneficiary_group is not set"]})
    if errors := preflight_errors(
        pks=config["pks"],
        master_detail=config["master_detail"],
        exclude_rdp_ids=exclude_rdp_ids,
    ):
        raise RdpWorkflowError({"errors": errors})


def rdp_creation_error(exc: IntegrityError) -> RdpWorkflowError:
    """Convert an RDP creation integrity error to a workflow error."""
    message = (
        "RDP: can not create while another RDP is unfinished"
        if "uniq_non_terminal_rdp_per_program" in str(exc)
        else "RDP: can not create record"
    )
    return RdpWorkflowError({"errors": [message]})


def schedule_rdp_processing(*, rdp: Rdp) -> None:
    """Schedule RDP operations or push evaluation when none are configured."""
    if rdp.operations.exists():
        schedule_rdp_operations(rdp=rdp)
    else:
        schedule_rdp_push_evaluation(rdp=rdp)


def create_rdp_core(job: AsyncJob) -> dict[str, Any]:
    """Create an RDP and schedule its processing."""
    config: CreateRdpConfig = job.config
    validate_rdp_creation(program=job.program, config=config)

    try:
        with transaction.atomic():
            program = Program.objects.select_for_update().get(pk=config["program_id"])
            if program.cleanup_in_progress:
                raise RdpWorkflowError({"errors": ["Program cleanup is in progress."]})

            rdp = create_rdp(config=config)
            AsyncJob.objects.filter(id=job.id).update(rdp=rdp)
            schedule_rdp_processing(rdp=rdp)
    except IntegrityError as exc:
        raise rdp_creation_error(exc) from exc

    return {"rdp_id": rdp.id}
