import pytest
from django.core.cache import cache
from country_workspace.models import MappingImporter
from country_workspace.cache.manager import cache_manager
from country_workspace.state import state


@pytest.mark.django_db
def test_mapping_importer_cache_invalidation_on_create_via_model(admin_user, country_office, data_checker_individual):
    """
    Test that creating a MappingImporter via the model (simulating global admin or shell)
    invalidates the cache keys expected by the workspace.
    """
    # Setup state
    state.tenant = country_office

    # 1. Simulate the list view being cached (both versioned and legacy key)
    # Legacy key
    legacy_key = f"mapping_importer_list:{country_office.pk}"
    cache.set(legacy_key, "cached_list", 300)

    # Versioned key (simulate view cache)
    initial_version = cache_manager.get_cache_version(office=country_office)

    # 2. Create MappingImporter via standard model (not Workspace Admin)
    MappingImporter.objects.create(
        name="hh_rules", office=country_office, data_checker=data_checker_individual, created_by=admin_user
    )

    # Cache version should be incremented
    new_version = cache_manager.get_cache_version(office=country_office)
    assert new_version > initial_version, "Office cache version should be incremented"


@pytest.mark.django_db
def test_mapping_importer_cache_invalidation_on_delete_via_model(admin_user, country_office, data_checker_individual):
    state.tenant = country_office

    # Create first
    mi = MappingImporter.objects.create(
        name="hh_rules_del", office=country_office, data_checker=data_checker_individual, created_by=admin_user
    )

    # Set cache
    legacy_key = f"mapping_importer_list:{country_office.pk}"
    cache.set(legacy_key, "cached_list", 300)
    initial_version = cache_manager.get_cache_version(office=country_office)

    # Delete
    mi.delete()

    # Assertions
    assert cache.get(legacy_key) is None, "Legacy cache key should be invalidated on delete"

    new_version = cache_manager.get_cache_version(office=country_office)
    assert new_version > initial_version, "Office cache version should be incremented on delete"
