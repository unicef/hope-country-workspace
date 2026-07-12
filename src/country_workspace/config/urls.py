import debug_toolbar
import django_select2.urls
from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.urls import path

from country_workspace.contrib.hope.views import DeduplicationCallbackView
from country_workspace.workspaces.sites import workspace

urlpatterns = [
    path(r"admin/", admin.site.urls),
    path(r"security/", include("unicef_security.urls", namespace="security")),
    path(r"social/", include("social_django.urls", namespace="social")),
    path(r"accounts/", include("django.contrib.auth.urls")),
    path(r"adminactions/", include("adminactions.urls")),
    path(r"sentry_debug/", lambda _: 1 / 0),
    path("select2/", include(django_select2.urls)),
    path(r"__debug__/", include(debug_toolbar.urls)),
    path(
        "api/dedup/callback/<str:signed_token>/",
        DeduplicationCallbackView.as_view(),
        name="dedup_callback",
    ),
]

if "django_browser_reload" in settings.INSTALLED_APPS:  # pragma: no cover
    urlpatterns += [path(r"__reload__/", include("django_browser_reload.urls"))]

urlpatterns += [path(r"", workspace.urls)]
