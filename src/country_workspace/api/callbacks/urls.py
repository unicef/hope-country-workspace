from django.urls import path

from .views import HopeRdpPushReadyCallbackView


app_name = "callbacks"

urlpatterns = [
    path(
        "hope/rdps/push-ready/<str:signed_token>/",
        HopeRdpPushReadyCallbackView.as_view(),
        name="hope-rdp-push-ready",
    ),
]
