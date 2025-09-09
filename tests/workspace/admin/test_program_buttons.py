import pytest
from django.contrib.admin import AdminSite
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse

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
def group_with_import_permissions():
    group = GroupFactory()
    import_permission = Permission.objects.get(
        codename="import_program_data",
        content_type__app_label="country_workspace",
    )
    group.permissions.add(import_permission)
    return group


@pytest.fixture
def user_with_import_permissions(group_with_import_permissions, country_program):
    user = UserFactory()
    UserRoleFactory(
        user=user,
        group=group_with_import_permissions,
        program=country_program,
        country_office=country_program.country_office,
    )
    return user


@pytest.fixture
def group_with_change_permissions():
    group = GroupFactory()
    change_permission = Permission.objects.get(
        codename="change_countryprogram",
        content_type__app_label="workspaces",
    )
    group.permissions.add(change_permission)
    return group


@pytest.fixture
def user_with_change_permissions(group_with_change_permissions, country_program):
    user = UserFactory()
    UserRoleFactory(
        user=user,
        group=group_with_change_permissions,
        program=country_program,
        country_office=country_program.country_office,
    )
    return user


@pytest.fixture
def login_and_select_tenant(client):
    def _login(user, program):
        client.force_login(user)
        client.post(reverse("workspace:select_tenant"), data={"tenant": program.country_office.pk})
        return client

    return _login


@pytest.fixture
def country_program_md_true(country_program):
    country_program.beneficiary_group.master_detail = True
    country_program.save()
    return country_program


@pytest.mark.django_db
def test_import_data_no_permissions(user, country_program_admin_instance, country_program):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user

    with pytest.raises(PermissionDenied):
        country_program_admin_instance.import_data(country_program_admin_instance, request, country_program.pk)


@pytest.mark.django_db  # ERA001
def test_import_data_with_permissions(
    user_with_import_permissions, country_program_admin_instance, country_program, client
):
    client.force_login(user_with_import_permissions)
    client.post(reverse("workspace:select_tenant"), data={"tenant": country_program.country_office.pk})
    url = reverse("workspace:workspaces_countryprogram_import_data", args=[country_program.pk])
    response = client.get(url)

    assert response.status_code == 200


@pytest.mark.django_db
def test_household_columns_no_permissions(user, country_program_admin_instance, country_program_md_true):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user

    with pytest.raises(PermissionDenied):
        country_program_admin_instance.household_columns(
            country_program_admin_instance, request, country_program_md_true.pk
        )


@pytest.mark.django_db
def test_household_columns_with_permissions(
    user_with_change_permissions, country_program_admin_instance, country_program_md_true, login_and_select_tenant
):
    client = login_and_select_tenant(user_with_change_permissions, country_program_md_true)
    url = reverse("workspace:workspaces_countryprogram_household_columns", args=[country_program_md_true.pk])
    response = client.get(url)

    assert response.status_code == 200


@pytest.mark.django_db
def test_individual_columns_no_permissions(user, country_program_admin_instance, country_program):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user

    with pytest.raises(PermissionDenied):
        country_program_admin_instance.individual_columns(country_program_admin_instance, request, country_program.pk)


@pytest.mark.django_db
def test_individual_columns_with_permissions(
    user_with_change_permissions, country_program_admin_instance, country_program, login_and_select_tenant
):
    client = login_and_select_tenant(user_with_change_permissions, country_program)
    url = reverse("workspace:workspaces_countryprogram_individual_columns", args=[country_program.pk])
    response = client.get(url)

    assert response.status_code == 200


@pytest.mark.django_db
def test_import_file_updates_no_permissions(user, country_program_admin_instance, country_program):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user

    with pytest.raises(PermissionDenied):
        country_program_admin_instance.import_file_updates(country_program_admin_instance, request, country_program.pk)


@pytest.mark.django_db
def test_import_file_updates_with_permissions(
    user_with_import_permissions, country_program_admin_instance, country_program, login_and_select_tenant
):
    client = login_and_select_tenant(user_with_import_permissions, country_program)
    url = reverse("workspace:workspaces_countryprogram_import_file_updates", args=[country_program.pk])
    response = client.get(url)

    assert response.status_code == 200
