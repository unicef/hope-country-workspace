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


def test_results_queue_uses_binding_keys(settings):
    queues = settings.STREAMING["QUEUES"]
    assert "binding_keys" in queues["results"]
    assert "routing" not in queues["results"]
