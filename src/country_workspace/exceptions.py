from django.http import Http404


class RemoteError(Http404):
    pass
