import hashlib
import re
import time
from typing import TYPE_CHECKING, Any, Generator, Final

import requests
from constance import config
from requests.exceptions import RequestException, HTTPError
from requests.adapters import HTTPAdapter
from country_workspace.exceptions import RemoteError

from .signals import hope_request_end, hope_request_start

if TYPE_CHECKING:
    JsonType = None | int | str | bool | list["JsonType"] | dict[str, "JsonType"]
    FlatJsonType = dict[str, str | int | bool]


TIMEOUTS: Final[tuple[int, int]] = (10, 20)  # (connect timeout, read timeout)


def sanitize_url(url: str) -> str:
    return re.sub(r"([^:]/)(/)+", r"\1", url)


class HopeClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or config.HOPE_API_TOKEN
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Token {self.token}"})
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=3))

    def _err(self, method: str, url: str, *, err: str, response: requests.Response | None = None) -> str:
        msg = f"HopeClient: {method} {url} failed: {err}"
        if response is None:
            return msg
        return f"{msg}. Status: {response.status_code}. Response: {response.text}"

    def get_url(self, path: str) -> str:
        url = sanitize_url(f"{config.HOPE_API_URL}/{path}")
        if not url.endswith("/"):
            url += "/"
        return url

    def get_lookup(self, path: str) -> "FlatJsonType":
        url = self.get_url(path)
        try:
            ret = self.session.get(url, timeout=TIMEOUTS)
        except RequestException as e:
            raise RemoteError(self._err("GET", url, err=str(e), response=getattr(e, "response", None))) from e
        if ret.status_code != 200:
            raise RemoteError(self._err("GET", url, err=f"unexpected status {ret.status_code}", response=ret))
        try:
            return ret.json()
        except ValueError as e:
            raise RemoteError(self._err("GET", url, err="invalid JSON response", response=ret)) from e

    def get(self, path: str, params: dict[str, Any] | None = None) -> "Generator[FlatJsonType, None, None]":
        url: str | None = self.get_url(path)
        signature = hashlib.sha256(f"{url}{params}{time.perf_counter_ns()}".encode()).hexdigest()
        pages = 0
        hope_request_start.send(self.__class__, url=url, params=params, signature=signature)

        while url:
            _url = url
            try:
                ret = self.session.get(_url, params=(params if pages == 0 else None), timeout=TIMEOUTS)
            except RequestException as e:
                raise RemoteError(self._err("GET", _url, err=str(e), response=getattr(e, "response", None))) from e

            if ret.status_code != 200:
                raise RemoteError(self._err("GET", _url, err=f"unexpected status {ret.status_code}", response=ret))

            pages += 1
            try:
                data = ret.json()
            except ValueError as e:
                raise RemoteError(self._err("GET", _url, err="invalid JSON response", response=ret)) from e

            try:
                yield from data["results"]
                url = data.get("next", None)
                if url and not data.get("results"):
                    break  # fallback in case the results are missing but next url is fulfilled
            except (TypeError, KeyError) as e:
                raise RemoteError(self._err("GET", _url, err="malformed JSON response", response=ret)) from e

        hope_request_end.send(self.__class__, url=url, params=params, pages=pages, signature=signature)

    def post(self, path: str, data: "JsonType | None") -> "FlatJsonType":
        url = self.get_url(path)
        signature = hashlib.sha256(f"{url}{data}{time.perf_counter_ns()}".encode()).hexdigest()
        hope_request_start.send(self.__class__, url=url, data=data, signature=signature)

        try:
            response = self.session.post(url, json=data, timeout=TIMEOUTS)

            # people endpoint
            if response.status_code == 400 and path.endswith("/push/people/"):
                try:
                    return {"errors": True, "people": response.json()}
                except ValueError as e:
                    raise RemoteError(self._err("POST", url, err="invalid JSON response", response=response)) from e

            response.raise_for_status()
            result = response.json()

        except HTTPError as e:
            raise RemoteError(self._err("POST", url, err=str(e), response=response)) from e
        except ValueError as e:
            raise RemoteError(self._err("POST", url, err="invalid JSON response", response=response)) from e
        except RequestException as e:
            raise RemoteError(self._err("POST", url, err=str(e), response=getattr(e, "response", None))) from e

        hope_request_end.send(self.__class__, url=url, data=data, signature=signature)
        return result
