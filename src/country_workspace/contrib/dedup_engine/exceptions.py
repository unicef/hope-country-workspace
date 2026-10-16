from country_workspace.exceptions import RemoteError


class DeduplicationSetGroupBusyError(RemoteError):
    """Raised when a deduplication set group is busy."""
