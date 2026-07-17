from requests import Response

from country_workspace.exceptions import RemoteError


class HopePushError(Exception):
    """Exception raised for errors during the push process."""


class HopeResponseError(RemoteError):
    """Exception raised for a non-successful HOPE HTTP response."""

    def __init__(self, message: str, *, response: Response) -> None:
        super().__init__(message)
        self.response = response

    @property
    def error_code(self) -> str | None:
        try:
            payload = self.response.json()
        except ValueError:
            return None

        error = payload.get("error") if isinstance(payload, dict) else None
        return error if isinstance(error, str) else None


class HopeSyncError(Exception):
    """Exception raised for errors during the synchronization process."""


class SkipRecordError(Exception):
    """Exception raised when a record should be skipped during synchronization process."""
