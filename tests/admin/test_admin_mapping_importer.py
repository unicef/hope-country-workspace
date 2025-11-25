from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from country_workspace.models import MappingImporter


if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", admin_user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


@pytest.fixture
def data_checker():
    from testutils.factories.smart_import import DataCheckerFactory

    return DataCheckerFactory()


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def mapping_importer(office, data_checker):
    return MappingImporter.objects.create(
        name="Test Mapping",
        description="Test mapping description",
        office=office,
        data_checker=data_checker,
        rules="gender=sex\nage=years",
    )


def test_admin_create_mapping_importer(app, data_checker, admin_user, office):
    """Test creating a mapping importer through admin sets created_by and office."""
    url = reverse("admin:country_workspace_mappingimporter_add")
    res = app.get(url)

    form = res.forms["mappingimporter_form"]
    form["data_checker"] = data_checker.id
    form["name"] = "Test Mapping"
    form["rules"] = "gender=sex"

    res = form.submit()
    assert res.status_code == 302

    new_mapping = MappingImporter.objects.get(name="Test Mapping")
    assert new_mapping.created_by == admin_user


def test_mapping_importer_apply_rules(mapping_importer):
    """Test that apply method correctly transforms field names."""
    data = {"gender": "male", "age": 25, "name": "John"}
    result = mapping_importer.apply(data)

    assert result == {"sex": "male", "years": 25, "name": "John"}
    assert "gender" not in result
    assert "age" not in result


def test_mapping_importer_apply_empty_rules():
    """Test that apply method with empty rules returns data unchanged."""
    mapping = MappingImporter(name="Empty", rules="")
    data = {"gender": "male", "age": 25}
    result = mapping.apply(data)

    assert result == data


def test_mapping_importer_unique_constraint(office, data_checker):
    """Test that mapping name must be unique per office."""
    from django.db import IntegrityError

    MappingImporter.objects.create(
        name="Duplicate",
        office=office,
        data_checker=data_checker,
    )

    with pytest.raises(IntegrityError):
        MappingImporter.objects.create(
            name="Duplicate",
            office=office,
            data_checker=data_checker,
        )


@patch("country_workspace.workspaces.admin.mapping_importer.cache")
def test_admin_save_invalidates_cache(mock_cache, app, data_checker, office, admin_user):
    """Test that saving a mapping invalidates the cache."""
    from country_workspace.state import state

    state.tenant = office

    url = reverse("admin:country_workspace_mappingimporter_add")
    res = app.get(url)

    form = res.forms["mappingimporter_form"]
    form["data_checker"] = data_checker.id
    form["name"] = "Cache Test Mapping"
    form["rules"] = "field1=field2"

    form.submit()

    # Verify cache.delete was called with the correct key
    mock_cache.delete.assert_called()
    call_args = mock_cache.delete.call_args[0]
    assert f"mapping_importer_list:{office.pk}" in call_args


def test_workspace_admin_queryset_filters_by_office(app, office, data_checker, admin_user):
    """Test that workspace admin only shows mappings for current office."""
    from country_workspace.state import state
    from testutils.factories import OfficeFactory

    other_office = OfficeFactory()

    # Create mapping for current office
    MappingImporter.objects.create(
        name="Office 1 Mapping",
        office=office,
        data_checker=data_checker,
    )

    # Create mapping for other office
    MappingImporter.objects.create(
        name="Office 2 Mapping",
        office=other_office,
        data_checker=data_checker,
    )

    state.tenant = office

    url = reverse("workspace:workspaces_countrymappingimporter_changelist")
    res = app.get(url)

    # Should only see the mapping from current office
    assert "Office 1 Mapping" in res.text
    assert "Office 2 Mapping" not in res.text


def test_admin_permissions_check_add(app, office, data_checker, admin_user):
    """Test that add permission is properly checked."""
    from country_workspace.state import state

    state.tenant = office

    # Remove add permission
    content_type = ContentType.objects.get_for_model(MappingImporter)
    permission = Permission.objects.get(
        codename="add_mappingimporter",
        content_type=content_type,
    )
    admin_user.user_permissions.remove(permission)

    url = reverse("workspace:workspaces_countrymappingimporter_add")
    res = app.get(url, expect_errors=True)

    assert res.status_code == 403


def test_admin_permissions_check_change(app, mapping_importer, admin_user):
    """Test that change permission is properly checked."""
    from country_workspace.state import state

    state.tenant = mapping_importer.office

    # Remove change permission
    content_type = ContentType.objects.get_for_model(MappingImporter)
    permission = Permission.objects.get(
        codename="change_mappingimporter",
        content_type=content_type,
    )
    admin_user.user_permissions.remove(permission)

    url = reverse("workspace:workspaces_countrymappingimporter_change", args=[mapping_importer.pk])
    res = app.get(url, expect_errors=True)

    assert res.status_code == 403


def test_admin_permissions_check_delete(app, mapping_importer, admin_user):
    """Test that delete permission is properly checked."""
    from country_workspace.state import state

    state.tenant = mapping_importer.office

    # Remove delete permission
    content_type = ContentType.objects.get_for_model(MappingImporter)
    permission = Permission.objects.get(
        codename="delete_mappingimporter",
        content_type=content_type,
    )
    admin_user.user_permissions.remove(permission)

    url = reverse("workspace:workspaces_countrymappingimporter_delete", args=[mapping_importer.pk])
    res = app.get(url, expect_errors=True)

    assert res.status_code == 403


@patch("country_workspace.workspaces.admin.mapping_importer.cache")
def test_admin_delete_invalidates_cache(mock_cache, app, mapping_importer, admin_user):
    """Test that deleting a mapping invalidates the cache."""
    from country_workspace.state import state

    state.tenant = mapping_importer.office

    url = reverse("workspace:workspaces_countrymappingimporter_delete", args=[mapping_importer.pk])
    res = app.get(url)
    form = res.forms["mappingimporter_form"]
    form.submit()

    # Verify cache.delete was called
    mock_cache.delete.assert_called()
    call_args = mock_cache.delete.call_args[0]
    assert f"mapping_importer_list:{mapping_importer.office.pk}" in call_args
