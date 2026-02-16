import re
from json import JSONDecodeError
from typing import Any, Final

import requests
from constance import config
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError, RequestException

from country_workspace.exceptions import RemoteError

TIMEOUTS: Final[tuple[int, int]] = (10, 20)  # (connect timeout, read timeout)


def sanitize_url(url: str) -> str:
    return re.sub(r"([^:]/)(/)+", r"\1", url)


class DeduplicationClient:
    def __init__(self, token: str | None = None, api_url: str | None = None) -> None:
        self.token = token or config.DEDUP_API_TOKEN
        self.api_url = api_url or config.DEDUP_API_URL
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Token {self.token}"})
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=3))

    def get_url(self, path: str) -> str:
        url = sanitize_url(f"{self.api_url}/{path}")
        if not url.endswith("/"):
            url += "/"
        return url

    def post(self, path: str, data: Any | None = None) -> dict[str, Any]:
        url = self.get_url(path)
        try:
            response = self.session.post(url, json=data, timeout=TIMEOUTS)  # nosec
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()
        except HTTPError as http_err:
            status = http_err.response.status_code if http_err.response else "N/A"
            body = http_err.response.text if http_err.response else "N/A"
            raise RemoteError(
                f"HTTP error posting to {url}: {http_err}. Status: {status}. Response Body: {body}"
            ) from http_err
        except JSONDecodeError as json_err:
            response_text = response.text if response else "N/A"
            raise RemoteError(
                f"Wrong JSON response posting to {url}. Status: {response.status_code}. Response text: {response_text}"
            ) from json_err
        except RequestException as req_err:
            raise RemoteError(f"Request failed for {url}: {req_err}") from req_err

    def upsert_deduplication_set(
        self,
        reference_pk: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
        notification_url: str = "",
        notify: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "reference_pk": reference_pk,
            "notify": notify,
            "notification_url": notification_url,
            "settings": settings or {},
        }
        if name:
            payload["name"] = name
        return self.post("deduplicationsets/", payload)

    def bulk_add_images(self, reference_pk: str, images: list[dict[str, str]]) -> dict[str, Any]:
        return self.post(f"deduplicationsets/{reference_pk}/images_bulk/", images)

    def process(self, reference_pk: str) -> dict[str, Any]:
        return self.post(f"deduplicationsets/{reference_pk}/process/", {})
