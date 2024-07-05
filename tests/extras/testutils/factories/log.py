from django.contrib.admin.models import LogEntry

from .base import AutoRegisterModelFactory


class LogEntryFactory(AutoRegisterModelFactory):
    level = "INFO"
    message = "Message for {{ event.name }} on channel {{channel.name}}"

    class Meta:
        model = LogEntry
