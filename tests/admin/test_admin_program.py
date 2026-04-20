from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryProgram


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    admin_user: "User",
) -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(admin_user)
    return django_app


def test_program_zap(app, program: "CountryProgram"):
    base_url = reverse("admin:country_workspace_program_zap", args=[program.pk])
    res = app.get(base_url, expect_errors=True)
    res = res.forms[1].submit()
    res = res.follow()
    assert res.status_code == 200


def test_program_clean_program(app, program: "CountryProgram"):
    base_url = reverse("admin:country_workspace_program_clean_program", args=[program.pk])
    res = app.get(base_url, expect_errors=True)
    confirmation_form = res.forms[1]
    res = confirmation_form.submit()
    res = res.follow()
    assert res.status_code == 200
