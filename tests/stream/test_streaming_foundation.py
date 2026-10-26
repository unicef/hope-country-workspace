import importlib
import os

from streaming.manager import ChangeManager, initialize_engine
from streaming.utils import check_callback

from country_workspace.stream.callbacks import handle_event
from country_workspace.stream.publish import publish


def test_handle_event_is_a_valid_callback():
    assert check_callback(handle_event) is True


def test_publish_succeeds_on_console_backend():
    assert publish("cw.test", {"hello": "cw"}) is True


def test_engine_uses_configured_manager_class(settings):
    manager = initialize_engine(True)
    assert isinstance(manager, ChangeManager)
    assert manager.backend.client_name == settings.STREAMING["CLIENT_NAME"]


def test_amqp_broker_url_is_rewritten_to_rabbit(monkeypatch):
    from country_workspace.config.fragments import streaming

    previous = os.environ.get("STREAMING_BROKER_URL")
    monkeypatch.setenv("STREAMING_BROKER_URL", "amqp://guest:guest@localhost:5672/vh")
    try:
        importlib.reload(streaming)
        assert streaming.STREAMING["BROKER_URL"] == "rabbit://guest:guest@localhost:5672/vh"
    finally:
        if previous is None:
            monkeypatch.delenv("STREAMING_BROKER_URL", raising=False)
        else:
            monkeypatch.setenv("STREAMING_BROKER_URL", previous)
        importlib.reload(streaming)


def test_ocr_results_queue_uses_binding_keys(settings):
    queues = settings.STREAMING["QUEUES"]
    assert queues["ocr_results"]["binding_keys"] == ["hcw.ocr.result"]
    assert "routing" not in queues["ocr_results"]
