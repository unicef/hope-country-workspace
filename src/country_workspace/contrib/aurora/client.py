from json import JSONDecodeError
from typing import Any, Generator, Final
from urllib.parse import urljoin

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from constance import config

from country_workspace.contrib.aurora.crypto import AuroraPayloadDecryptor, ENCRYPTED_CONTENT_TYPE
from country_workspace.exceptions import RemoteError


TIMEOUTS: Final[tuple[int, int]] = (10, 20)  # (connect timeout, read timeout)


class AuroraClient:
    """
    A client for interacting with the Aurora API.

    Provides methods to fetch data from the Aurora API with authentication.
    Handles pagination automatically for large datasets.
    """

    def __init__(self, token: str | None = None, api_url: str | None = None) -> None:
        """
        Initialize the AuroraClient.

        Args:
            token (str | None): An optional API token for authentication. If not provided,
                the token is retrieved from the Constance configuration (config.AURORA_API_TOKEN).
            api_url (str | None): An optional API url. If not provided, the url will be retrieved
                from the Constance configuration (config.AURORA_API_URL).

        """
        self.token = token or config.AURORA_API_TOKEN
        self.api_url = api_url or config.AURORA_API_URL
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Token {self.token}"})
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=3))
        encryption_key: str = getattr(settings, "AURORA_PAYLOAD_ENCRYPTION_KEY", "")
        self._decryptor: AuroraPayloadDecryptor | None = (
            AuroraPayloadDecryptor(encryption_key) if encryption_key else None
        )

    def _get_url(self, path: str) -> str:
        """
        Construct a fully qualified URL for the Aurora API.

        Args:
            path (str): The relative API path.

        Returns:
            str: The full URL, ensuring it ends with a trailing slash.

        """
        base = self.api_url if self.api_url.endswith("/") else self.api_url + "/"
        url = urljoin(base, path)
        if not url.endswith("/"):
            url += "/"
        return url

    def get(self, path: str, params: dict[str, Any] | None = None) -> Generator[dict[str, Any], None, None]:
        """
        Yield every record from a paginated Aurora endpoint.

        Args:
            path: Relative API path.
            params: Optional query parameters forwarded to every paginated request.

        When ``AURORA_PAYLOAD_ENCRYPTION_KEY`` is configured, automatically adds
        ``Accept: application/encrypted+json`` and decrypts each page.

        """
        url = self._get_url(path)
        extra_headers: dict[str, str] = {"Accept": ENCRYPTED_CONTENT_TYPE} if self._decryptor else {}
        while url:
            data = self._fetch_page(url, params, extra_headers)
            yield from data["results"]
            url = data.get("next")

    def _fetch_page(
        self,
        url: str,
        params: dict[str, Any] | None,
        extra_headers: dict[str, str],
    ) -> dict[str, Any]:
        """Fetch a single paginated page, decrypt if the response signals it."""
        try:
            ret = self.session.get(url, params=params, timeout=TIMEOUTS, headers=extra_headers)  # nosec
            ret.raise_for_status()
        except requests.RequestException as e:
            raise RemoteError(f"Remote Error fetching {url}: {e}") from e

        content_type = ret.headers.get("Content-Type", "")
        if self._decryptor and ENCRYPTED_CONTENT_TYPE in content_type:
            return self._decryptor.decrypt(ret.text)  # type: ignore[return-value]
        try:
            return ret.json()
        except JSONDecodeError as e:
            raise RemoteError(f"Wrong JSON response fetching {url}") from e
