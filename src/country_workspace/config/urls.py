from django.conf.urls import include
from django.contrib import admin
from django.urls import path

import debug_toolbar

from country_workspace.workspaces.sites import workspace

urlpatterns = [
    path(r"admin/", admin.site.urls),
    path(r"security/", include("unicef_security.urls", namespace="security")),
    path(r"social/", include("social_django.urls", namespace="social")),
    path(r"accounts/", include("django.contrib.auth.urls")),
    path(r"adminactions/", include("adminactions.urls")),
    path(r"sentry_debug/", lambda _: 1 / 0),
    path(r"__debug__/", include(debug_toolbar.urls)),
    path(r"", workspace.urls),
]

admin.site.site_header = "Workspace Admin"
admin.site.site_title = "Workspace Admin Portal"
admin.site.index_title = "Welcome to HOPE Workspace"
