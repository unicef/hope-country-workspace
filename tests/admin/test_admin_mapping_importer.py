from typing import TYPE_CHECKING

import pytest
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


def test_admin_create_mapping_importer(app, data_checker, admin_user):
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
