from contextlib import suppress
from urllib.parse import urlsplit
from uuid import UUID

from constance import config
from django.core import signing
from django.urls import reverse

from .constants import DEDUP_CALLBACK_SALT


def get_dedup_callback_base_url() -> str:
    """Return a validated base URL for DedupEngine callbacks."""
    base_url = config.APP_BASE_URL.strip().rstrip("/")

    with suppress(ValueError):
        url = urlsplit(base_url)
        if url.scheme in {"http", "https"} and url.hostname and not (url.query or url.fragment):
            _ = url.port
            return base_url

    raise ValueError("APP_BASE_URL must be a valid absolute HTTP(S) URL.")


def build_dedup_operation_callback_url(*, operation_id: UUID) -> str:
    """Build a signed DedupEngine callback URL for an RDP operation."""
    token = signing.dumps({"operation_id": str(operation_id)}, salt=DEDUP_CALLBACK_SALT)
    path = reverse("api:callbacks:dedup-engine-rdp-state-changed", kwargs={"signed_token": token})
    return f"{get_dedup_callback_base_url()}{path}"
