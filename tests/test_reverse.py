from django.urls import reverse


def test_reverse():
    assert reverse("admin:index") == "/admin/"
    assert reverse("workspace:index") == "/"
