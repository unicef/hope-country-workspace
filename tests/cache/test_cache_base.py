from typing import TYPE_CHECKING

import pytest
from django.core.cache import cache
from django.urls import reverse
from testutils.perms import user_grant_permissions
from testutils.utils import select_office

from country_workspace.cache.manager import CacheManager

if TYPE_CHECKING:
    from django.db.models import Model
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User
    from country_workspace.workspaces.models import CountryIndividual


def pytest_generate_tests(metafunc: "Metafunc") -> None:  # noqa
    import django

    from country_workspace.models import Household, Individual, Program
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram

    django.setup()
    if "model" in metafunc.fixturenames:
        m2: list[Model] = []
        ids = []
        for model in (Household, Individual, CountryHousehold, CountryIndividual, Program, CountryProgram):
            name = model._meta.object_name
            full_name = f"{model._meta.app_label}.{name}"
            m2.append(model)
            ids.append(full_name)
        metafunc.parametrize("model", m2, ids=ids)


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables", user: "User") -> "CWTestApp":
    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(user)
    django_app._user = user
    return django_app


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def manager():
    m = CacheManager()
    m.init()
    cache.clear()
    return m


@pytest.fixture
def individual(program):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        household__batch__program=program, household__batch__country_office=program.country_office
    )


def test_cache_changelist(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with user_grant_permissions(app._user, "workspaces.view_countryindividual", individual.program):
        with select_office(app, individual.country_office, individual.program):
            res = app.get(url)
            assert res.status_code == 200, res.location
            etag = res.headers["Etag"]
            res = app.get(url, headers={"etag": etag})
            assert res.status_code == 304, res.location
            assert res.headers["Etag"] == etag

            individual.save()
            res = app.get(url, headers={"etag": etag})
            assert res.status_code == 200, res.location
            assert res.headers["Etag"] != etag
