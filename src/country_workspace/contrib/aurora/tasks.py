from typing import Any
from django.contrib.contenttypes.models import ContentType
from country_workspace.models import AsyncJob
from country_workspace.admin.sync import ContextAuroraSyncHandler, SyncConfig as ContextAuroraSyncConfig
from country_workspace.contrib.aurora.context_aurora import SyncStep


def sync_from_aurora(job: AsyncJob) -> dict[str, Any]:
    ct = ContentType.objects.get_for_id(job.config["ct_id"])
    cfg = ContextAuroraSyncConfig(
        model=ct.model_class(), step=SyncStep[job.config["step"]], sync_handler=ContextAuroraSyncHandler()
    )
    return cfg["sync_handler"].sync(step=cfg["step"])
