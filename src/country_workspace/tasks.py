import io
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from hope_smart_import.readers import open_xls

from country_workspace.config.celery import app
from country_workspace.models import AsyncJob


@app.task()
def sync_job_task(pk: int, version: int) -> dict[str, Any]:
    job: AsyncJob = AsyncJob.objects.select_related("program").get(pk=pk, version=version)
    if job.type == AsyncJob.JobType.BULK_UPDATE_IND:
        return bulk_update_individual(job)


def bulk_update_individual(job: AsyncJob) -> dict[str, Any]:
    ret = {"not_found": []}
    for e in open_xls(io.BytesIO(job.file.read()), start_at=0):
        try:
            _id = e.pop("id")
            ind = job.program.individuals.get(id=_id)
            ind.flex_fields.update(**e)
            ind.save()
        except ObjectDoesNotExist:
            ret["not_found"].append(_id)
    return ret
