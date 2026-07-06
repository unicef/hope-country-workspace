from typing import Any

from django.core.files.storage import storages
from django.core.management import BaseCommand


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
            self.stdout.write(self.style.SUCCESS("Created HOPE blob container."))
        except Exception as e:  # noqa: BLE001
            self.stdout.write(f"HOPE blob container not created ({e.__class__.__name__}); assuming it already exists.")
