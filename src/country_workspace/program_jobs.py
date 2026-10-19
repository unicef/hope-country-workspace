from collections.abc import Iterable
from typing import Any

from django.db import transaction

from country_workspace.models import AsyncJob, Program


def schedule_program_jobs(*, program: Program, jobs: Iterable[dict[str, Any]]) -> list[AsyncJob] | None:
    """Schedule new Program jobs unless cleanup is in progress."""
    with transaction.atomic():
        program = Program.objects.select_for_update().get(pk=program.pk)
        if program.cleanup_in_progress:
            return None

        scheduled = [AsyncJob.objects.create(program=program, **kwargs) for kwargs in jobs]
        for job in scheduled:
            transaction.on_commit(job.queue)

    return scheduled


def schedule_program_job(*, program: Program, **kwargs: Any) -> AsyncJob | None:
    """Schedule new Program job unless cleanup is in progress."""
    jobs = schedule_program_jobs(program=program, jobs=(kwargs,))
    return None if jobs is None else jobs[0]
