from urllib.parse import urlparse

from django.core.cache import cache

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.models import Project, Registration
from country_workspace.contrib.hope.sync.office import sync_programs
from country_workspace.models import AsyncJob, SyncLog


def sync_all(job: AsyncJob) -> dict[str, int]:
    """
    Synchronize programs from the HOPE core, as well as projects and registrations from the Aurora system.

    Args:
        job (AsyncJob): The job instance that triggered the synchronization.

    Returns:
        dict[str, int]: A dictionary with sync statistics for each entity type.

    """
    client = AuroraClient()
    with cache.lock("sync-aurora"):
        return {
            "programs": sync_programs(),
            "projects": sync_projects(client),
            "registrations": sync_registrations(client),
        }


def sync_projects(client: AuroraClient) -> dict[str, int]:
    """
    Synchronize projects from the Aurora system.

    Args:
        client (AuroraClient): The client instance used to fetch project data.

    Returns:
        dict[str, int]: A dictionary with sync statistics for projects.

    """
    totals = {"add": 0, "upd": 0}
    for record in client.get("project"):
        __, created = Project.objects.get_or_create(
            reference_pk=record["id"],
            defaults={
                "name": record["name"],
            },
        )
        totals["add" if created else "upd"] += 1
    SyncLog.objects.register_sync(Project)
    return totals


def sync_registrations(client: AuroraClient) -> dict[str, int]:
    """
    Synchronize registrations from the Aurora system.

    Args:
        client (AuroraClient): The client instance used to fetch project data.

    Returns:
        dict[str, int]: A dictionary with sync statistics for registrations.

    """
    totals = {"add": 0, "upd": 0}
    for record in client.get("registration"):
        extracted_id = _extract_related_id(record["project"])
        if extracted_id is None:
            totals.setdefault("skip", []).append(record["id"])
            continue
        try:
            project = Project.objects.get(reference_pk=extracted_id)
        except Project.DoesNotExist:
            totals.setdefault("skip", []).append(record["id"])
            continue

        _, created = project.registrations.get_or_create(
            reference_pk=record["id"],
            defaults={
                "name": record["name"],
                "active": record["active"],
            },
        )
        totals["add" if created else "upd"] += 1
    SyncLog.objects.register_sync(Registration)
    return totals


def _extract_related_id(url: str) -> int | None:
    """Extract the related object ID from the given URL.

    Args:
        url (str): A URL string that is expected to end with the object's ID as its last path segment.

    Returns:
        int | None: The extracted ID if successful, otherwise None.

    """
    parsed_url = urlparse(url)
    try:
        related_id = parsed_url.path.rstrip("/").split("/")[-1]
        return int(related_id)
    except (ValueError, IndexError):
        return None
