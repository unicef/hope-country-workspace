from django.apps import AppConfig


class StreamConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "country_workspace.stream"
    verbose_name = "Streaming"

    def ready(self) -> None:
        from streaming.manager import initialize_engine

        initialize_engine()
