from django.urls import path

from .dedup_engine.views import DedupEngineRdpStateChangedCallbackView
from .hope.views import HopeRdpPushReadyCallbackView


app_name = "callbacks"

urlpatterns = [
    path(
        "dedup-engine/rdps/state-changed/<str:signed_token>/",
        DedupEngineRdpStateChangedCallbackView.as_view(),
        name="dedup-engine-rdp-state-changed",
    ),
    path(
        "hope/rdps/push-ready/",
        HopeRdpPushReadyCallbackView.as_view(),
        name="hope-rdp-push-ready",
    ),
]
