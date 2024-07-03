from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from cryptography.hazmat.primitives import serialization


def clean_key(value: str) -> str:
    return value.replace("\n", "").replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")


class Command(BaseCommand):
    requires_migrations_checks = False
    output_transaction = False
    requires_system_checks = []

    def handle(self, *args: Any, **options: Any) -> str | None:
        from py_vapid import b64urlencode, Vapid02

        print("Add this env vars\n")
        if not settings.PUSH_NOTIFICATIONS_SETTINGS["WP_PRIVATE_KEY"]:
            vapid = Vapid02(conf=args)
            vapid.generate_keys()
            KEY = clean_key(vapid.private_pem().decode())
        else:
            KEY = clean_key(settings.PUSH_NOTIFICATIONS_SETTINGS["WP_PRIVATE_KEY"])
        vapid = Vapid02.from_string(KEY)
        raw_pub = vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        claims = settings.PUSH_NOTIFICATIONS_SETTINGS["WP_CLAIMS"]
        auth = vapid.sign(claims)
        print(f"export WP_PRIVATE_KEY={KEY}")
        print(f"export WP_APPLICATION_SERVER_KEY={b64urlencode(raw_pub)}")
        print(f"export WP_VAPID={auth['Authorization']}")
        print()
