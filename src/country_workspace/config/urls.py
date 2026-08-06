import debug_toolbar
import django_select2.urls
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from country_workspace.workspaces.sites import workspace

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/rest/", include("country_workspace.api.urls", namespace="api")),
    path("security/", include("unicef_security.urls", namespace="security")),
    path("social/", include("social_django.urls", namespace="social")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("adminactions/", include("adminactions.urls")),
    path("select2/", include(django_select2.urls)),
    path("__debug__/", include(debug_toolbar.urls)),
]

if settings.DEBUG:  # pragma: no cover
    urlpatterns += [path("sentry_debug/", lambda _: 1 / 0)]

if "django_browser_reload" in settings.INSTALLED_APPS:  # pragma: no cover
    urlpatterns += [path("__reload__/", include("django_browser_reload.urls"))]

urlpatterns += [path("", workspace.urls)]
