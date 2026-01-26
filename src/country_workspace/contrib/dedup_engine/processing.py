from typing import Any, TYPE_CHECKING
from requests.exceptions import RequestException

from country_workspace.models import AsyncJob, Rdp
from .client import Status, make_client
from .response import Status as ResponseStatus

if TYPE_CHECKING:
    from .request import Image


STUB_SET_FIRST: tuple[str, ...] = (
    "Aaron_Eckhart_0001.jpg",
    "Aaron_Guiel_0001.jpg",
    "Aaron_Peirsol_0001.jpg",
    "Cathy_Freeman_0001.jpg",
)

STUB_SET_NEXT: tuple[str, ...] = (
    "Aaron_Peirsol_0002.jpg",
    "Cathy_Freeman_0002.jpg",
    "Ziwang_Xu_0001.jpg",
    "Zoe_Ball_0001.jpg",
)


def dedup(job: AsyncJob) -> dict[str, Any]:
    """Run DedupEngine pipeline for the program tied to this job (demo stub images)."""
    program_code = job.program.code
    filenames = STUB_SET_FIRST if Rdp.objects.filter(program_id=job.program_id).count() == 1 else STUB_SET_NEXT
    images: list[Image] = [{"reference_pk": f"ref_{f}", "filename": f} for f in filenames]

    client = make_client(program_code)
    try:
        client.deduplicate(images=images, settings={})
    finally:
        client.session.close()

    return {"deduplication_set_group__reference_id": program_code, "images": len(images)}


def fetch_dedup_status(program_id: str) -> "Status | None":
    """Fetch DedupEngine status or None if the service is unreachable or errored."""
    client = make_client(program_id)
    try:
        return client.status()
    except RequestException:
        return Status(ResponseStatus.UNKNOWN, -1, None)
    finally:
        client.session.close()
