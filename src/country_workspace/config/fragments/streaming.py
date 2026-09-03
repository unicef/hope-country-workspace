from .. import env

STREAMING_BROKER_URL = env("STREAMING_BROKER_URL")

if STREAMING_BROKER_URL.startswith("amqp://"):
    STREAMING_BROKER_URL = STREAMING_BROKER_URL.replace("amqp://", "rabbit://", 1)

STREAMING = {
    "BROKER_URL": STREAMING_BROKER_URL,
    "CLIENT_NAME": "country-workspace",
    "MANAGER_CLASS": "streaming.manager.ChangeManager",
    "LISTEN_CALLBACK": "country_workspace.stream.callbacks.handle_event",
    "QUEUES": {
        "ocr_results": {
            "binding_keys": ["hcw.ocr.result"],
        },
    },
}
