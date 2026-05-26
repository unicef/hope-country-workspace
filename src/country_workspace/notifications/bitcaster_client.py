import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class RetryableBitcasterError(Exception):
    """Raised when an event delivery can be retried safely."""


class BitcasterClient:
    """A generic client for interacting with the Bitcaster REST API."""

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

    def trigger_event(self, event_name: str, payload: dict[str, Any]) -> bool:
        """
        Trigger an event in Bitcaster.

        Args:
            event_name: The name of the event/signal in Bitcaster.
            payload: A dictionary of context data to send to Bitcaster.

        Returns:
            bool: True if the request was successful, False otherwise.

        """
        if not self.is_configured:
            logger.warning("Bitcaster client is not fully configured. Skipping event '%s'.", event_name)
            return False

        endpoint = (
            f"{self.api_url}/api/o/{self.organization_slug}/p/{self.project_slug}/"
            f"a/{self.application_slug}/e/{event_name}/trigger/"
        )

        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            data = {"context": payload}

            response = requests.post(endpoint, json=data, headers=headers, timeout=10)
            if response.status_code >= 500:
                raise RetryableBitcasterError(
                    f"Bitcaster server error while triggering event '{event_name}': {response.status_code}"
                )
            response.raise_for_status()
            logger.info("Successfully triggered Bitcaster event: %s", event_name)
        except requests.exceptions.HTTPError:
            raise
        except requests.exceptions.RequestException as e:
            raise RetryableBitcasterError(f"Network error while triggering '{event_name}'") from e

        return True
