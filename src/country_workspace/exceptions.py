from django.http import Http404


class RemoteError(Http404):
    pass


class HttpErrorRedirect(Exception):
    def __init__(self, url):
        self.url = url
