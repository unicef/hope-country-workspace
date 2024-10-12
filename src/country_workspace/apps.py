from django.apps import AppConfig


class Config(AppConfig):
    name = __name__.rpartition(".")[0]
    verbose_name = "Country Workspace"

    def ready(self) -> None:
        from .utils import flags  # noqa
