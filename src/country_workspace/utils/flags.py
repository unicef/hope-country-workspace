import logging
import os
import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpRequest

from adminfilters.utils import parse_bool
from flags.conditions import conditions

from country_workspace.state import state

from .http import get_client_ip

logger = logging.getLogger(__name__)


def validate_bool(value: Any) -> None:
    if not str(value).lower() in [
        "true",
        "1",
        "yes",
        "t",
        "y",
        "false",
        "0",
        "no",
        "f",
        "n",
    ]:
        raise ValidationError("Enter a valid bool")
    return parse_bool(value)


@conditions.register("superuser", validator=validate_bool)
def superuser(value: str, request: "HttpRequest|None", **kwargs: "Any") -> bool:
    return request.user.is_superuser == parse_bool(value)


@conditions.register("debug", validator=validate_bool)
def debug(value: str, **kwargs: "Any") -> bool:
    return settings.DEBUG == parse_bool(value)


@conditions.register("hostname")
def hostname(value: str, request: "HttpRequest|None", **kwargs: "Any") -> bool:
    return request.get_host().split(":")[0] in value.split(",")


@conditions.register("Environment Variable")
def env_var(value: str, **kwargs: Any) -> bool:
    if "=" in value:
        key, value = value.split("=")
        return os.environ.get(key, -1) == value
    else:
        return value.strip() in os.environ


@conditions.register("HTTP Request Header")
def header_key(value: str, **kwargs: Any) -> bool:
    if "=" in value:
        key, value = value.split("=")
        key = f"HTTP_{key.strip()}"
        try:
            return bool(re.compile(value).match(state.request.META.get(key, "")))
        except re.error:
            return False
    else:
        value = f"HTTP_{value.strip()}"
        return value in state.request.META


try:
    import pytricia

    pyt = pytricia.PyTricia()

    def client_ip(value: str, **kwargs: Any) -> bool:
        remote = get_client_ip()
        pyt.insert(value, "")
        return remote in pyt

except ImportError:
    logger.warning("pytricia not installed. 'client_ip' flag not registared ")

    def client_ip(value: str, **kwargs: Any) -> bool:
        pass


conditions.register("User IP", client_ip)
