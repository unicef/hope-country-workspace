class RdpWorkflowError(Exception):
    """Raised when an RDP workflow cannot complete."""


class PushThresholdConfirmationError(Exception):
    """Require confirmation before pushing an RDP."""
