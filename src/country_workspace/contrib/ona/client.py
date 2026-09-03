from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests

from .exceptions import OnaApiError, OnaAuthenticationError, OnaRateLimitError


class OnaClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: int = 30,
        page_size: int = 500,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.page_size = page_size

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"

        response = requests.get(
            url,
            headers=self.headers,
            params=params or {},
            timeout=self.timeout,
        )

        if response.status_code in (401, 403):
            raise OnaAuthenticationError("ONA authentication failed")

        if response.status_code == 429:
            raise OnaRateLimitError("ONA rate limit reached")

        if response.status_code >= 400:
            raise OnaApiError(f"ONA API error {response.status_code}: {response.text[:500]}")

        return response.json()

    def get_form_metadata(self, form_id: str | int) -> dict[str, Any]:
        return self.get(f"/api/v1/forms/{form_id}")

    def get_submissions_page(
        self,
        *,
        form_id: str | int,
        start: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        data = self.get(
            f"/api/v1/data/{form_id}",
            params={
                "start": start,
                "limit": limit or self.page_size,
            },
        )

        if not isinstance(data, list):
            raise OnaApiError("ONA submissions response must be a list")

        return data

    def iter_submissions(self, form_id: str | int) -> Iterator[dict[str, Any]]:
        start = 0

        while True:
            submissions = self.get_submissions_page(
                form_id=form_id,
                start=start,
                limit=self.page_size,
            )

            if not submissions:
                break

            yield from submissions

            if len(submissions) < self.page_size:
                break

            start += self.page_size