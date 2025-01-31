from django.contrib.admin.sites import site
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from smart_admin.console import panel_migrations, panel_redis, panel_sentry, panel_sysinfo
from smart_admin.smart_auth.admin import ContentTypeAdmin, PermissionAdmin

from ..cache.smart_panel import panel_cache
from .batch import BatchAdmin  # noqa
from .household import HouseholdAdmin  # noqa
from .individual import IndividualAdmin  # noqa
from .job import AsyncJobAdmin  # noqa
from .locations import AreaAdmin, AreaTypeAdmin, CountryAdmin  # noqa
from .office import OfficeAdmin  # noqa
from .program import ProgramAdmin  # noqa
from .registration import RegistrationAdmin  # noqa
from .role import UserRoleAdmin  # noqa
from .sync import SyncLog  # noqa
from .user import UserAdmin  # noqa

site.register(ContentType, admin_class=ContentTypeAdmin)
site.register(Permission, admin_class=PermissionAdmin)


site.register_panel(panel_sentry)
site.register_panel(panel_cache)
site.register_panel(panel_sysinfo)
site.register_panel(panel_migrations)
site.register_panel(panel_redis)
