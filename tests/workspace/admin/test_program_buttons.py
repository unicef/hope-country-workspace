import pytest
from django.contrib.admin import AdminSite
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from country_workspace.workspaces.admin import CountryProgramAdmin
from country_workspace.workspaces.models import CountryProgram
from testutils.factories import CountryProgramFactory, OfficeFactory, GroupFactory, UserFactory, UserRoleFactory


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def country_program_admin_instance(admin_site) -> CountryProgramAdmin:
    return CountryProgramAdmin(CountryProgram, admin_site)


@pytest.fixture
def country_office():
    return OfficeFactory()


@pytest.fixture
def country_program(country_office):
    return CountryProgramFactory(country_office=country_office)


@pytest.fixture
def group_with_permissions():
    group = GroupFactory()
    import_permission = Permission.objects.get(
        codename="import_program_data",
        content_type__app_label="country_workspace",
    )
    group.permissions.add(import_permission)
    return group


@pytest.fixture
def user_with_permissions(group_with_permissions, country_program):
    user = UserFactory()
    UserRoleFactory(
        user=user,
        group=group_with_permissions,
        program=country_program,
        country_office=country_program.country_office,
    )
    return user


@pytest.mark.django_db
def test_import_data_no_permissions(user, country_program_admin_instance, country_program):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user

    with pytest.raises(PermissionDenied):
        country_program_admin_instance.import_data(country_program_admin_instance, request, country_program.pk)
