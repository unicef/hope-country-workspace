import pytest
from django.test import RequestFactory
from unittest.mock import Mock
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from country_workspace.workspaces.handlers import OfficeBasedPermissionHandler
from testutils.factories import UserFactory, OfficeFactory, CountryProgramFactory, UserRoleFactory, GroupFactory


@pytest.fixture
def permission_handler():
    return OfficeBasedPermissionHandler("test_permission")


@pytest.fixture
def office():
    return OfficeFactory()


@pytest.fixture
def program(office):
    return CountryProgramFactory(country_office=office)


@pytest.fixture
def request_factory():
    return RequestFactory()


def test_superuser_permissions(permission_handler, program, request_factory):
    superuser = UserFactory(is_superuser=True)
    regular_user = UserFactory(is_superuser=False)

    superuser_request = request_factory.get("/")
    superuser_request.user = superuser

    regular_user_request = request_factory.get("/")
    regular_user_request.user = regular_user

    assert permission_handler(superuser_request, program) is True
    assert permission_handler(regular_user_request, program) is False


def test_no_country_office_returns_false(permission_handler, request_factory):
    user = UserFactory(is_superuser=False)
    request = request_factory.get("/")
    request.user = user

    mock_obj = Mock()
    mock_obj.country_office = None

    result = permission_handler(request, mock_obj)
    assert result is False


def test_user_roles_filtering(permission_handler, program, request_factory):
    user = UserFactory(is_superuser=False)
    different_office = OfficeFactory()
    group = GroupFactory()

    request = request_factory.get("/")
    request.user = user

    UserRoleFactory(user=user, country_office=different_office, group=group, program=None)

    result = permission_handler(request, program)
    assert result is False

    UserRoleFactory(user=user, country_office=program.country_office, group=group, program=None)

    result = permission_handler(request, program)
    assert result is False


def test_user_with_matching_role_and_permission_returns_true(permission_handler, program, request_factory):
    user = UserFactory(is_superuser=False)
    different_program = CountryProgramFactory(country_office=program.country_office)
    group1 = GroupFactory()
    group2 = GroupFactory()

    content_type = ContentType.objects.get_for_model(group1)
    permission = Permission.objects.create(
        codename="test_permission", name="Test Permission", content_type=content_type
    )
    group2.permissions.add(permission)

    request = request_factory.get("/")
    request.user = user

    UserRoleFactory(user=user, country_office=program.country_office, group=group1, program=different_program)

    UserRoleFactory(user=user, country_office=program.country_office, group=group2, program=program)

    result = permission_handler(request, program)
    assert result is True
