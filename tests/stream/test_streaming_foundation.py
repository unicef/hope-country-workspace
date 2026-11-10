import importlib
import os

from django.conf import settings
from pytest_mock import MockerFixture
from streaming.manager import ChangeManager, initialize_engine
from streaming.utils import check_callback

from country_workspace.stream import PublishOutcome, publish
from country_workspace.stream.callbacks import OCR_RESULT_ROUTING_KEY, handle_event


def test_handle_event_is_a_valid_callback() -> None:
    assert check_callback(handle_event) is True


def test_publish_succeeds_on_console_backend() -> None:
    assert publish("cw.test", {"hello": "cw"}) is PublishOutcome.SUCCESS


def test_engine_uses_configured_manager_class() -> None:
    manager = initialize_engine(True)
    assert isinstance(manager, ChangeManager)
    assert manager.backend.client_name == settings.STREAMING["CLIENT_NAME"]


def test_amqp_broker_url_is_rewritten_to_rabbit(mocker: MockerFixture) -> None:
    from country_workspace.config.fragments import streaming

    environment = mocker.patch.dict(os.environ, {"STREAMING_BROKER_URL": "amqp://guest:guest@localhost:5672/vh"})
    try:
        importlib.reload(streaming)
        assert streaming.STREAMING["BROKER_URL"] == "rabbit://guest:guest@localhost:5672/vh"
    finally:
        mocker.stop(environment)
        importlib.reload(streaming)


def test_ocr_results_queue_uses_binding_keys() -> None:
    from country_workspace.config.fragments import streaming

    queues = streaming.STREAMING["QUEUES"]
    assert queues["ocr_results"]["binding_keys"] == [OCR_RESULT_ROUTING_KEY]
    assert "routing" not in queues["ocr_results"]
