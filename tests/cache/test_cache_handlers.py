from typing import TYPE_CHECKING
from unittest import mock

import pytest
from django.core.cache import cache
from testutils.factories import get_factory_for_model

from country_workspace.cache.manager import CacheManager

if TYPE_CHECKING:
    from django.db.models import Model


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
def manager(worker_id):
    m = CacheManager(f"cache{worker_id}")
    m.init()
    cache.clear()
    return m


def test_handlers(manager, model):
    fc = get_factory_for_model(model)
    obj = fc()
    with mock.patch("country_workspace.cache.handlers.cache_manager", manager):
        program = getattr(obj, "program", obj)
        v1 = manager.get_cache_version(program=program)
        obj.save()
        v2 = manager.get_cache_version(program=program)
        assert v2 > v1
