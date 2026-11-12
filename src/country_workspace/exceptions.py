from django.http import Http404


class RemoteError(Http404):
    pass


class RemoteUnavailableError(Exception):
    pass


class BlobStorageError(RemoteUnavailableError):
    pass


class MissingFlexFileError(Exception):
    """A flex field references a `FlexFieldFile` the record does not own."""


class InvalidAccountAttachmentError(Exception):
    """An account attachment breaks a limit HOPE enforces on account attachments."""
