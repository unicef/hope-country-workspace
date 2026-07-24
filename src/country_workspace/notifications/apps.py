from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "country_workspace.notifications"

    def ready(self) -> None:
        # Import handlers to ensure signals are registered when Django starts
        import country_workspace.notifications.handlers  # noqa: F401
