class HopePushError(Exception):
    """Exception raised for errors during the push process."""


class HopeSyncError(Exception):
    """Exception raised for errors during the synchronization process."""


class SkipRecordError(Exception):
    """Exception raised when a record should be skipped during synchronization process."""
