import logging
from typing import Any
from urllib.parse import urlparse

from bitcaster_sdk.client import Client as SDKClient
from django.conf import settings

logger = logging.getLogger(__name__)


class NotifyError(Exception):
    """Raised when a Bitcaster notification fails."""


class BitcasterManager:
    """Client wrapper around bitcaster-sdk."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        organization_slug: str | None = None,
        project_slug: str | None = None,
        application_slug: str | None = None,
    ) -> None:
        # Allow overriding settings, but default to Django settings
        self.api_url = api_url or settings.BITCASTER_API_URL
        self.api_key = api_key or settings.BITCASTER_API_KEY
        self.organization_slug = organization_slug or settings.BITCASTER_ORGANIZATION_SLUG
        self.project_slug = project_slug or settings.BITCASTER_PROJECT_SLUG
        self.application_slug = application_slug or settings.BITCASTER_APPLICATION_SLUG

    @property
    def is_configured(self) -> bool:
        return bool(
            self.api_url and self.api_key and self.organization_slug and self.project_slug and self.application_slug
        )

    def _build_bae(self) -> str:
        parsed = urlparse(self.api_url)
        return f"{parsed.scheme}://{self.api_key}@{parsed.netloc}/api/o/{self.organization_slug}/"

    def trigger_event(self, event_name: str, payload: dict[str, Any]) -> bool:
        if not self.is_configured:
            logger.warning("Bitcaster client is not fully configured. Skipping event '%s'.", event_name)
            return False

        try:
            SDKClient(bae=self._build_bae()).trigger(
                project=self.project_slug,
                application=self.application_slug,
                event=event_name,
                context=payload,
            )
        except Exception as exc:
            raise NotifyError(f"SDK call failed for event '{event_name}': {exc}") from exc
        logger.info("Successfully triggered Bitcaster event: %s", event_name)
        return True
