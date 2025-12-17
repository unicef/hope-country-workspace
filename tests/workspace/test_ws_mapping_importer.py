import pytest
from django.core.cache import cache
from country_workspace.models import MappingImporter
from country_workspace.cache.manager import cache_manager
from country_workspace.state import state


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.mark.django_db
def test_mapping_importer_cache_invalidation_on_create_via_model(admin_user, office, individual_checker):
    """
    Test that creating a MappingImporter via the model (simulating global admin or shell)
    invalidates the cache keys expected by the workspace.
    """
    # Setup state
    state.tenant = office

    # 1. Simulate the list view being cached (both versioned and legacy key)
    # Legacy key
    legacy_key = f"mapping_importer_list:{office.pk}"
    cache.set(legacy_key, "cached_list", 300)

    # Versioned key (simulate view cache)
    initial_version = cache_manager.get_cache_version(office=office)

    # 2. Create MappingImporter via standard model (not Workspace Admin)
    MappingImporter.objects.create(
        name="hh_rules", office=office, data_checker=individual_checker, created_by=admin_user
    )

    # Cache version should be incremented
    new_version = cache_manager.get_cache_version(office=office)
    assert new_version > initial_version, "Office cache version should be incremented"


@pytest.mark.django_db
def test_mapping_importer_cache_invalidation_on_delete_via_model(admin_user, office, individual_checker):
    state.tenant = office

    # Create first
    mi = MappingImporter.objects.create(
        name="hh_rules_del", office=office, data_checker=individual_checker, created_by=admin_user
    )

    # Set cache
    legacy_key = f"mapping_importer_list:{office.pk}"
    cache.set(legacy_key, "cached_list", 300)
    initial_version = cache_manager.get_cache_version(office=office)

    # Delete
    mi.delete()

    # Assertions
    new_version = cache_manager.get_cache_version(office=office)
    assert new_version > initial_version, "Office cache version should be incremented on delete"
