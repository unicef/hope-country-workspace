from urllib.parse import urlparse
from django.core.cache import cache

from country_workspace.models import SyncLog
from country_workspace.contrib.aurora.models import Project, Registration
from country_workspace.contrib.aurora.client import AuroraClient


def sync_projects() -> dict[str, int]:
    """Synchronize projects from the Aurora system and updates the local database.

    Returns:
        dict[str, int]: A dictionary containing the number of projects added and updated:
            - "add": Number of new projects created.
            - "upd": Number of existing projects updated.

    """
    client = AuroraClient()
    totals = {"add": 0, "upd": 0}
    with cache.lock("sync-projects"):
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


def sync_registrations(limit_to_project: Project | None = None) -> dict[str, int]:
    """Synchronize registrations from the Aurora system and update the local database.

    Args:
        limit_to_project (Project | None, optional): If provided, only registrations
            related to this project will be synchronized.

    Returns:
        dict[str, int]: A dictionary with the number of registrations processed:
            - "add": Number of new registrations created.
            - "upd": Number of existing registrations updated.
            - "skip": Number of registrations skipped due to a missing project or an invalid project reference.

    """
    client = AuroraClient()
    totals = {"add": 0, "upd": 0, "skip": 0}

    with cache.lock("sync-registrations"):
        resource = f"project/{limit_to_project.reference_pk}/registrations/" if limit_to_project else "registration"

        for record in client.get(resource):
            if limit_to_project:
                project = limit_to_project
            else:
                extracted_id = _extract_related_id(record["project"])
                if extracted_id is None:
                    totals["skip"] += 1
                    continue
                try:
                    project = Project.objects.get(reference_pk=extracted_id)
                except Project.DoesNotExist:
                    totals["skip"] += 1
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
