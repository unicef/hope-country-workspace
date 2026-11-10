from uuid import uuid4

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.rdp.deduplication import callbacks


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org", "https://example.org"),
        ("https://example.org/", "https://example.org"),
    ],
)
def test_get_dedup_callback_base_url(url: str, expected: str) -> None:
    with override_config(APP_BASE_URL=url):
        assert callbacks.get_dedup_callback_base_url() == expected


@pytest.mark.parametrize("url", ["", "example.org", "ftp://example.org", "https://example.org/?a=1"])
def test_get_dedup_callback_base_url_rejects_invalid_url(url: str) -> None:
    with override_config(APP_BASE_URL=url):
        with pytest.raises(ValueError, match="valid absolute HTTP"):
            callbacks.get_dedup_callback_base_url()


def test_build_dedup_operation_callback_url(mocker: MockerFixture) -> None:
    operation_id = uuid4()
    mocker.patch.object(callbacks, "get_dedup_callback_base_url", return_value="https://example.org")
    dumps = mocker.patch.object(callbacks.signing, "dumps", return_value="TOKEN")
    reverse = mocker.patch.object(callbacks, "reverse", return_value="/callback/TOKEN/")

    assert callbacks.build_dedup_operation_callback_url(operation_id=operation_id) == (
        "https://example.org/callback/TOKEN/"
    )

    dumps.assert_called_once_with(
        {"operation_id": str(operation_id)},
        salt=callbacks.DEDUP_CALLBACK_SALT,
    )
    reverse.assert_called_once_with(
        "api:callbacks:dedup-engine-rdp-state-changed",
        kwargs={"signed_token": "TOKEN"},
    )
