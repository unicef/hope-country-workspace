from django.urls import path

from .views import HopeRdiCallbackView


app_name = "api"

urlpatterns = [
    path(
        "callbacks/hope/rdis/<str:hope_rdi_id>/",
        HopeRdiCallbackView.as_view(),
        name="hope-rdi-callback",
    ),
]
