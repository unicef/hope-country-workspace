import pytest
from streaming.config import CONFIG
from streaming.manager import initialize_engine


@pytest.fixture(autouse=True)
def streaming_test_engine(settings):
    """Reset django-streaming config/engine so tests see pytest STREAMING overrides."""
    settings.STREAMING = {
        "BROKER_URL": "console://",
        "CLIENT_NAME": "country-workspace-test",
        "MANAGER_CLASS": "streaming.manager.ChangeManager",
        "LISTEN_CALLBACK": "country_workspace.stream.callbacks.handle_event",
        "QUEUES": {
            "ocr_results": {"binding_keys": ["hcw.ocr.result"]},
        },
    }
    CONFIG.load()
    initialize_engine(True)
