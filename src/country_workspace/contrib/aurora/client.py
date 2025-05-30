from json import JSONDecodeError
from typing import Any, Generator
from urllib.parse import urljoin

import requests
from constance import config

from country_workspace.exceptions import RemoteError


class AuroraClient:
    """
    A client for interacting with the Aurora API.

    Provides methods to fetch data from the Aurora API with authentication.
    Handles pagination automatically for large datasets.
    """

    def __init__(self, token: str | None = None) -> None:
        """
        Initialize the AuroraClient.

        Args:
            token (str | None): An optional API token for authentication. If not provided,
                the token is retrieved from the Constance configuration (config.AURORA_API_TOKEN).

        """
        self.token = token or config.AURORA_API_TOKEN

    def _get_url(self, path: str) -> str:
        """
        Construct a fully qualified URL for the Aurora API.

        Args:
            path (str): The relative API path.

        Returns:
            str: The full URL, ensuring it ends with a trailing slash.

        """
        url = urljoin(config.AURORA_API_URL, path)
        if not url.endswith("/"):
            url = url + "/"
        return url

    def get(self, path: str, params: dict[str, Any] | None = None) -> Generator[dict[str, Any], None, None]:
        """Fetch records from the Aurora API with automatic pagination."""
        url = self._get_url(path)
        while url:
            try:
                ret = requests.get(url, params=params, headers={"Authorization": f"Token {self.token}"}, timeout=10)
                ret.raise_for_status()
            except requests.RequestException as e:
                raise RemoteError(f"Remote Error fetching {url}: {e}") from e

            try:
                data = ret.json()
            except JSONDecodeError as e:
                raise RemoteError(f"Wrong JSON response fetching {url}") from e

            yield from data["results"]
            url = data.get("next")
