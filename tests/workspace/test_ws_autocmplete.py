from django.urls import reverse

import pytest
from django_webtest import DjangoTestApp
from django_webtest.pytest_plugin import MixinWithInstanceVariables
from responses import RequestsMock
from testutils.utils import select_office


@pytest.fixture()
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture()
def app(django_app_factory: "MixinWithInstanceVariables", mocked_responses: "RequestsMock") -> "DjangoTestApp":
    from testutils.factories.user import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_project_autocomplete(app: DjangoTestApp, program) -> None:
    url = reverse("workspace:autocomplete")
    with select_office(app, program.country_office):
        res = app.get(url, expect_errors=True)
        assert res.status_code == 403

        res = app.get(f"{url}?app_label=country_workspace&model_name=batch&field_name=program")
        assert res.status_code == 200
