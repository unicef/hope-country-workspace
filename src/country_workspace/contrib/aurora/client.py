from typing import Any, Generator
from urllib.parse import urljoin

import requests
from constance import config


class AuroraClient:

    def __init__(self, token: str | None = None) -> None:
        self.token = token or config.AURORA_API_TOKEN

    def _get_url(self, path: str) -> str:
        url = urljoin(config.AURORA_API_URL, path)
        if not url.endswith("/"):
            url = url + "/"
        return url

    def get(self, path: str) -> Generator[dict[str, Any], None, None]:
        url = self._get_url(path)
        while url:
            print(f"{url=}")
            ret = requests.get(url, headers={"Authorization": f"Token {self.token}"}, timeout=10)
            if ret.status_code != 200:
                raise Exception(f"Error {ret.status_code} fetching {url}")
            data = ret.json()

            for record in data["results"]:
                yield record

            url = data.get("next")
