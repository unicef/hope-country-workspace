from django.conf import settings
from django.contrib.auth.models import Group, Permission


def get_or_create_defaults_group() -> "Group":
    reporter, created = Group.objects.get_or_create(name=settings.ANALYST_GROUP_NAME)
    # if created:
    for perm in Permission.objects.order_by("codename").filter(
        content_type__app_label="country_workspace", codename__startswith="view_"
    ):
        reporter.permissions.add(perm)

    return reporter
