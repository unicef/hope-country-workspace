class HopePushError(Exception):
    """Exception raised for errors during the push process."""


class HopeRdiCallbackError(Exception):
    """Exception raised for errors during HOPE RDI callback processing."""


class HopeRdiCallbackNotFoundError(HopeRdiCallbackError):
    """Exception raised when no RDP matches the HOPE RDI ID."""


class HopeRdiCallbackConflictError(HopeRdiCallbackError):
    """Exception raised when the HOPE RDI callback conflicts with the current RDP state."""


class HopeSyncError(Exception):
    """Exception raised for errors during the synchronization process."""


class SkipRecordError(Exception):
    """Exception raised when a record should be skipped during synchronization process."""
