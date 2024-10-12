import os
from unittest import mock

from django.test.client import RequestFactory

import pytest

from country_workspace.state import state
from country_workspace.utils.flags import client_ip, env_var, header_key


@pytest.mark.parametrize(
    "subnet, ip, result",
    [
        ("192.168.1.0/24", "192.168.1.1", True),
        ("192.168.1.1/32", "192.168.1.1", True),
        ("192.168.1.1", "192.168.1.1", True),
        ("192.168.1.0/24", "192.168.66.1", False),
        ("192.168.0.0/16", "192.168.1.1", True),
    ],
)
def test_client_ip(rf: RequestFactory, subnet: str, ip: str, result: str) -> None:
    request = rf.get("/", REMOTE_ADDR=ip)
    with state.configure(request=request):
        assert client_ip(subnet) == result


@pytest.mark.parametrize(
    "value, result",
    [
        ("LOGGING_LEVEL=CRITICAL", True),
        ("LOGGING_LEVEL=WARN", False),
        ("LOGGING_LEVEL", True),
        ("ERROR", False),
    ],
)
def test_env_var(value: str, result: str) -> None:
    with mock.patch.dict(os.environ, {"LOGGING_LEVEL": "CRITICAL"}, clear=True):
        assert env_var(value) == result


@pytest.mark.parametrize(
    "value, result",
    [
        ("CUSTOM_KEY=123", True),
        ("CUSTOM_KEY", True),
        ("CUSTOM_KEY=234", False),
        ("MISSING=222", False),
        ("MISSING", False),
        ("ERROR=[", False),
    ],
)
def test_header_key(rf: "RequestFactory", value: str, result: str) -> None:

    request = rf.get("/", HTTP_CUSTOM_KEY="123")
    with state.configure(request=request):
        assert header_key(value) == result
