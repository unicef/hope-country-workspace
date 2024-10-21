from typing import Any, Generator
from urllib.parse import urljoin

from django.conf import settings

import requests
from constance import config


class AuroraClient:

    def __init__(self, token: str | None = None) -> None:
        self.token = token or settings.AURORA_API_TOKEN
        # temporarily for development purposes
        self.use_mock = True

    def _get_url(self, path: str) -> str:
        url = urljoin(config.AURORA_API_URL, path)
        if not url.endswith("/"):
            url = url + "/"
        return url

    def _load_mock_data(self, path: str) -> dict:
        import json
        from pathlib import Path

        file_path = (
            Path(__file__).resolve().parent.parent.parent.parent.parent / "tests" / "extras" / "aurora_record.json"
        )
        if file_path.exists():
            with file_path.open() as f:
                return json.load(f)
        raise FileNotFoundError(f"Mock data for {path} not found")

    def get(self, path: str) -> Generator[dict[str, Any], None, None]:
        if self.use_mock:
            data = self._load_mock_data(path)
        else:
            url = self._get_url(path)
            ret = requests.get(url, headers={"Authorization": f"Token {self.token}"}, timeout=10)
            if ret.status_code != 200:
                raise Exception(f"Error {ret.status_code} fetching {url}")
            data = ret.json()

        for record in data["results"]:
            yield record

        if not self.use_mock and "next" in data:
            url = data["next"]
        else:
            url = None
