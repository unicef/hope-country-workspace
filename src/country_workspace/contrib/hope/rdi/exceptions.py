from country_workspace.exceptions import RemoteError


class HopeRdiResetUnconfirmedError(RemoteError):
    """Raised when CW cannot confirm whether HOPE accepted an RDI reset."""
