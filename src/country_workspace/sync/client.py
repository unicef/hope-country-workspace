from typing import TYPE_CHECKING, Generator, Optional, Union
from urllib.parse import urljoin

from django.conf import settings

import requests
from constance import config

from country_workspace.exceptions import RemoteError

if TYPE_CHECKING:
    JsonType = Union[None, int, str, bool, list["JsonType"], dict[str, "JsonType"]]
    FlatJsonType = dict[str, Union[str, int, bool]]


class HopeClient:

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.HOPE_API_TOKEN

    def get_url(self, path: str) -> str:
        url = urljoin(config.HOPE_API_URL, path)
        if not url.endswith("/"):
            url = url + "/"
        return url

    def get_lookup(self, path: str) -> "FlatJsonType":
        url = self.get_url(path)
        ret = requests.get(url, headers={"Authorization": f"Token {self.token}"})  # nosec
        if ret.status_code != 200:
            raise RemoteError(f"Error {ret.status_code} fetching {url}")
        return ret.json()

    def get(self, path: str) -> "Generator[FlatJsonType, None, None]":
        url: "str|None" = self.get_url(path)
        while True:
            if not url:
                break
            ret = requests.get(url, headers={"Authorization": f"Token {self.token}"})  # nosec
            if ret.status_code != 200:
                raise RemoteError(f"Error {ret.status_code} fetching {url}")
            data = ret.json()
            for record in data["results"]:
                yield record
            if "next" in data:
                url = data["next"]
            else:
                url = None
