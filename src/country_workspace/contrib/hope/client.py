import hashlib
import re
import time
from json import JSONDecodeError
from typing import TYPE_CHECKING, Any, Generator

import requests
from constance import config
from requests.exceptions import RequestException, HTTPError

from country_workspace.exceptions import RemoteError

from .signals import hope_request_end, hope_request_start

if TYPE_CHECKING:
    JsonType = None | int | str | bool | list["JsonType"] | dict[str, "JsonType"]
    FlatJsonType = dict[str, str | int | bool]


def sanitize_url(url: str) -> str:
    return re.sub(r"([^:]/)(/)+", r"\1", url)


class HopeClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or config.HOPE_API_TOKEN

    def get_url(self, path: str) -> str:
        url = sanitize_url(f"{config.HOPE_API_URL}/{path}")
        if not url.endswith("/"):
            url = url + "/"
        return url

    def get_lookup(self, path: str) -> "FlatJsonType":
        url = self.get_url(path)
        ret = requests.get(url, headers={"Authorization": f"Token {self.token}"}, timeout=60)  # nosec
        if ret.status_code != 200:
            raise RemoteError(f"Error {ret.status_code} fetching {url}")
        return ret.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> "Generator[FlatJsonType, None, None]":
        url: "str|None" = self.get_url(path)
        signature = hashlib.sha256(f"{url}{params}{time.perf_counter_ns()}".encode()).hexdigest()
        pages = 0
        hope_request_start.send(self.__class__, url=url, params=params, signature=signature)
        while url:
            try:
                ret = requests.get(
                    url,
                    params=(params if pages == 0 else None),
                    headers={"Authorization": f"Token {self.token}"},
                    timeout=10,
                )  # nosec
                if ret.status_code != 200:
                    raise RemoteError(f"Error {ret.status_code} fetching {url}")
            except RequestException:
                raise RemoteError(f"Remote Error fetching {url}")

            pages += 1

            try:
                data = ret.json()
            except JSONDecodeError:
                raise RemoteError(f"Wrong JSON response fetching {url}")
            try:
                yield from data["results"]
                url = data.get("next", None)
                if url and not data.get("results"):
                    break  # fallback in case the results are missing but next url is fulfilled
            except TypeError:
                raise RemoteError(f"Malformed JSON fetching {url}")
        hope_request_end.send(self.__class__, url=url, params=params, pages=pages, signature=signature)

    def post(self, path: str, data: "JsonType | None") -> "FlatJsonType":
        url = self.get_url(path)
        signature = hashlib.sha256(f"{url}{data}{time.perf_counter_ns()}".encode()).hexdigest()
        hope_request_start.send(self.__class__, url=url, data=data, signature=signature)

        try:
            response = requests.post(
                url,
                json=data,
                headers={"Authorization": f"Token {self.token}"},
                timeout=10,  # nosec
            )

            # people endpoint
            if response.status_code == 400 and path.endswith("/push/people/"):
                return {"errors": True, "people": response.json()}

            response.raise_for_status()
            result = response.json()

        except HTTPError as http_err:
            resp = http_err.response
            error_details = resp.text[:1000] + "..." if len(resp.text) > 1000 else resp.text
            raise RemoteError(
                f"HTTP error posting to {url}: {http_err}. Status: {resp.status_code}. Response Body: {error_details}"
            ) from http_err
        except requests.exceptions.JSONDecodeError as json_err:
            response_text = response.text if response else "N/A"
            raise RemoteError(
                f"Wrong JSON response posting to {url}. Status: {response.status_code}. Response text: {response_text}"
            ) from json_err
        except RequestException as req_err:
            raise RemoteError(f"Request failed for {url}: {req_err}") from req_err

        hope_request_end.send(self.__class__, url=url, data=data, signature=signature)
        return result
