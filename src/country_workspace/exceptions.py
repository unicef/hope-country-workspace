from django.http import Http404


class RemoteError(Http404):
    pass


class RemoteUnavailableError(Exception):
    pass


class MissingFlexFileError(Exception):
    """A flex field references a `FlexFieldFile` the record does not own."""
