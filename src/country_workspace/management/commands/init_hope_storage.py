from typing import Any

from azure.core.exceptions import AzureError, ResourceExistsError
from django.core.files.storage import storages
from django.core.management import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Ensure the shared HOPE blob container exists (idempotent; intended for local Azurite dev)."
    requires_migrations_checks = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> None:
        storage = storages["hope"]
        client = getattr(storage, "client", None)
        if client is None or not hasattr(client, "create_container"):
            self.stdout.write("STORAGES['hope'] is not an Azure backend; nothing to do.")
            return
        try:
            client.create_container()
        except ResourceExistsError:
            self.stdout.write("HOPE blob container already exists.")
        except AzureError as e:
            raise CommandError(f"Failed to create HOPE blob container: {e.__class__.__name__}: {e}") from e
        else:
            self.stdout.write(self.style.SUCCESS("Created HOPE blob container."))
