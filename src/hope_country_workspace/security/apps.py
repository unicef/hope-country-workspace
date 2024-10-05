from django.apps import AppConfig
from django.conf import settings
from django.contrib.auth.signals import user_logged_in


class Config(AppConfig):
    name = "hope_country_workspace.security"
    verbose_name = "Security"

    def ready(self):
        pass


def do_stuff(sender, user, request, **kwargs):
    if user.email in settings.SUPERUSERS or user.username in settings.SUPERUSERS:
        user.is_superuser = True
        user.is_staff = True
        user.save()


user_logged_in.connect(do_stuff)
