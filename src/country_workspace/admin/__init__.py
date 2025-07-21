from django.contrib.admin.sites import site
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from smart_admin.console import panel_migrations, panel_redis, panel_sentry, panel_sysinfo
from smart_admin.smart_auth.admin import ContentTypeAdmin, PermissionAdmin

from ..cache.smart_panel import panel_cache
from .batch import BatchAdmin
from .beneficiary_group import BeneficiaryGroupAdmin
from .constance import ConstanceAdmin
from .household import HouseholdAdmin
from .individual import IndividualAdmin
from .job import AsyncJobAdmin
from .locations import AreaAdmin, AreaTypeAdmin, CountryAdmin
from .mapping_importer import MappingImporterAdmin
from .office import OfficeAdmin
from .program import ProgramAdmin
from .rdp import RdpAdmin
from .role import UserRoleAdmin
from .sync_log import SyncLog
from .user import UserAdmin
from .serializer import DataSerializerAdmin

site.register(ContentType, admin_class=ContentTypeAdmin)
site.register(Permission, admin_class=PermissionAdmin)

site.register_panel(panel_sentry)
site.register_panel(panel_cache)
site.register_panel(panel_sysinfo)
site.register_panel(panel_migrations)
site.register_panel(panel_redis)

__all__ = [
    "AreaAdmin",
    "AreaTypeAdmin",
    "AsyncJobAdmin",
    "BatchAdmin",
    "BeneficiaryGroupAdmin",
    "ConstanceAdmin",
    "CountryAdmin",
    "DataSerializerAdmin",
    "HouseholdAdmin",
    "IndividualAdmin",
    "MappingImporterAdmin",
    "OfficeAdmin",
    "ProgramAdmin",
    "RdpAdmin",
    "SyncLog",
    "UserAdmin",
    "UserRoleAdmin",
]
