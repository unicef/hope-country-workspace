from unittest.mock import MagicMock

from django.http import HttpResponse

from hope_country_workspace.middleware.state import StateClearMiddleware, StateSetMiddleware


def test_set(rf, user):
    request = rf.get("/")
    request.user = user
    get_response = MagicMock(side_effect=HttpResponse("Ok"))
    res = StateSetMiddleware(get_response)(request)
    assert res == b"Ok"


def test_clear(rf, user):
    request = rf.get("/")
    request.user = user
    get_response = MagicMock(side_effect=HttpResponse("Ok"))
    res = StateClearMiddleware(get_response)(request)
    assert res == b"Ok"
