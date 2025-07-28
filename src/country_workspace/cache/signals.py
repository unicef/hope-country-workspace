from typing import Any

import django.dispatch
from django.db.backends.signals import connection_created
from django.dispatch import receiver

cache_get = django.dispatch.Signal()
cache_set = django.dispatch.Signal()
cache_store = django.dispatch.Signal()
cache_invalidate = django.dispatch.Signal()


@receiver(connection_created)
def db_connection_created(*_: Any, **__: Any) -> None:
    from .manager import cache_manager

    cache_manager.init()
