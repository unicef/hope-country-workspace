from urllib.parse import urljoin

from django.conf import settings

import requests
from constance import config


class HopeClient:

    def __init__(self, token=None):
        self.token = token or settings.HOPE_API_TOKEN

    def get_url(self, path):
        url = urljoin(config.HOPE_API_URL, path)
        if not url.endswith("/"):
            url = url + "/"
        return url

    def get_lookup(self, path):
        url = self.get_url(path)
        ret = requests.get(url, headers={"Authorization": f"Token {self.token}"})  # nosec
        if ret.status_code != 200:
            raise requests.exceptions.HTTPError(f"Error {ret.status_code} fetching {url}")
        return ret.json()

    def get(self, path):
        url = self.get_url(path)
        while True:
            ret = requests.get(url, headers={"Authorization": f"Token {self.token}"})  # nosec
            if ret.status_code != 200:
                raise requests.exceptions.HTTPError(f"Error {ret.status_code} fetching {url}")
            data = ret.json()
            for record in data["results"]:
                yield record
            if "next" in data:
                url = data["next"]
            else:
                url = None
            if not url:
                break

        return True
