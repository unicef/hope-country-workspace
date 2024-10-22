from django.contrib.admin import site
from django.contrib.contenttypes.models import ContentType

from smart_admin.smart_auth.admin import ContentTypeAdmin

from .batch import BatchAdmin  # noqa
from .household import HouseholdAdmin  # noqa
from .individual import IndividualAdmin  # noqa
from .locations import AreaAdmin, AreaTypeAdmin, CountryAdmin  # noqa
from .office import OfficeAdmin  # noqa
from .program import ProgramAdmin  # noqa
from .role import UserRoleAdmin  # noqa
from .sync import SyncLog  # noqa
from .user import UserAdmin  # noqa

site.register(ContentType, admin_class=ContentTypeAdmin)
