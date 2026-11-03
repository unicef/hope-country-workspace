from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    OnaApiError,
    OnaAttachmentTooLargeError,
    OnaAuthenticationError,
    OnaNotFoundError,
    OnaRateLimitError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from requests import Response

DOWNLOAD_CHUNK_SIZE = 64 * 1024


class OnaClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: int = 30,
        page_size: int = 500,
        max_download_bytes: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.page_size = page_size
        self.max_download_bytes = max_download_bytes
        self.session = Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset(("GET",)),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"

        response = self.session.get(
            url,
            headers=self.headers,
            params=params or {},
            timeout=self.timeout,
        )
        self._raise_for_status(response)

        return response.json()

    def download(self, url: str) -> bytes:
        """Return the content of an attachment `download_url`, relative or absolute.

        The body is streamed, so no more than `max_download_bytes` is ever held
        for a single attachment.
        """
        if urlsplit(url).netloc:
            if not url.startswith(f"{self.base_url}/"):
                raise OnaApiError(f"ONA attachment URL is outside {self.base_url}: {url}")
        else:
            url = f"{self.base_url}/{url.lstrip('/')}"

        with self.session.get(
            url,
            headers={"Authorization": f"Token {self.token}"},
            timeout=self.timeout,
            stream=True,
        ) as response:
            self._raise_for_status(response)

            limit = self.max_download_bytes
            if limit is not None and int(response.headers.get("Content-Length") or 0) > limit:
                raise OnaAttachmentTooLargeError(f"ONA attachment exceeds {limit} bytes: {url}")

            content = bytearray()
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                content.extend(chunk)
                if limit is not None and len(content) > limit:
                    raise OnaAttachmentTooLargeError(f"ONA attachment exceeds {limit} bytes: {url}")

        return bytes(content)

    @staticmethod
    def _raise_for_status(response: Response) -> None:
        if response.status_code in (401, 403):
            raise OnaAuthenticationError("ONA authentication failed")

        if response.status_code in (404, 410):
            raise OnaNotFoundError(f"ONA resource not found ({response.status_code}): {response.url}")

        if response.status_code == 429:
            raise OnaRateLimitError("ONA rate limit reached")

        if response.status_code >= 400:
            raise OnaApiError(f"ONA API error {response.status_code}: {response.text[:500]}")

    def get_form_metadata(self, form_id: str | int) -> dict[str, Any]:
        return self.get(f"/api/v1/forms/{form_id}")

    def get_submissions_page(
        self,
        *,
        form_id: str | int,
        start: int,
        limit: int | None = None,
        last_id: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "start": start,
            "limit": limit or self.page_size,
            "sort": json.dumps({"_id": 1}),
        }
        if last_id is not None:
            params["query"] = json.dumps({"_id": {"$gt": last_id}})

        data = self.get(
            f"/api/v1/data/{form_id}",
            params=params,
        )

        if not isinstance(data, list):
            raise OnaApiError("ONA submissions response must be a list")

        return data

    def iter_submissions(self, form_id: str | int, *, last_id: int | None = None) -> Iterator[dict[str, Any]]:
        start = 0

        while True:
            submissions = self.get_submissions_page(
                form_id=form_id,
                start=start,
                limit=self.page_size,
                last_id=last_id,
            )

            if not submissions:
                break

            yield from submissions
            start += len(submissions)
