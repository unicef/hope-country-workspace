from typing import TYPE_CHECKING

import pytest
from testutils.perms import user_grant_permissions

from country_workspace.cache.manager import CacheManager
from country_workspace.state import state

if TYPE_CHECKING:
    from django.db.models import Model
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from testutils.types import CWTestApp

    from country_workspace.models import User


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
def manager(worker_id):
    m = CacheManager(f"cache{worker_id}")
    m.init()
    return m


def test_cache_manager_init():
    pass


def test_cache_manager_build_key_from_request(app, manager, program, rf, worker_id):
    request = rf.get("/")
    assert manager.build_key_from_request(request) == f"cache{worker_id}:entry:view:-:ts:v:t:p::"

    with user_grant_permissions(
        app._user, "workspaces.view_countryhousehold", country_office_or_program=program.country_office
    ):
        with state.set(tenant=program.country_office, program=program):
            key = manager.build_key_from_request(request)
            assert key.startswith(f"cache{worker_id}:")
            assert program.country_office.slug in key


def test_invalidate(manager, program):
    manager.reset_cache_version(program=program)
    v = manager.get_cache_version(program=program)
    assert v == 1

    manager.incr_cache_version(program=program)
    v = manager.get_cache_version(program=program)
    assert v == 2

    manager.incr_cache_version(program=program)
    v = manager.get_cache_version(program=program)
    assert v == 3


def test_invalidate_pattern_no_matches(manager):
    manager.store("test:key", "value")

    deleted_count = manager.invalidate_pattern("nonexistent:*")

    assert deleted_count == 0
    assert manager.retrieve("test:key") == "value"


def test_invalidate_containing(manager):
    manager.store("prefix:user:123:data", "value1")
    manager.store("prefix:user:123:settings", "value2")
    manager.store("prefix:user:456:data", "value3")
    manager.store("prefix:order:789", "value4")

    assert manager.retrieve("prefix:user:123:data") == "value1"
    assert manager.retrieve("prefix:user:123:settings") == "value2"
    assert manager.retrieve("prefix:user:456:data") == "value3"
    assert manager.retrieve("prefix:order:789") == "value4"

    deleted_count = manager.invalidate_containing("user:123")

    assert deleted_count == 2
    assert manager.retrieve("prefix:user:123:data") is None
    assert manager.retrieve("prefix:user:123:settings") is None

    assert manager.retrieve("prefix:user:456:data") == "value3"
    assert manager.retrieve("prefix:order:789") == "value4"


def test_invalidate_containing_no_matches(manager):
    manager.store("test:key", "value")

    deleted_count = manager.invalidate_containing("nonexistent")

    assert deleted_count == 0
    assert manager.retrieve("test:key") == "value"
