from requests import Response

from country_workspace.exceptions import RemoteError


class HopeResponseError(RemoteError):
    """Exception raised for a non-successful HOPE HTTP response."""

    def __init__(self, message: str, *, response: Response) -> None:
        super().__init__(message)
        self.response: Response = response


class HopeSyncError(Exception):
    """Exception raised for errors during the synchronization process."""


class SkipRecordError(Exception):
    """Exception raised when a record should be skipped during synchronization process."""
