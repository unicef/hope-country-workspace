from django.urls import path

from .hope.views import HopeRdpPushReadyCallbackView


app_name = "callbacks"

urlpatterns = [
    path(
        "hope/rdps/push-ready/",
        HopeRdpPushReadyCallbackView.as_view(),
        name="hope-rdp-push-ready",
    ),
]
