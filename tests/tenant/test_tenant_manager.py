from typing import TYPE_CHECKING
from unittest import mock

import pytest

from hope_country_workspace.state import state
from hope_country_workspace.tenant.db import TenantManager
from hope_country_workspace.tenant.exceptions import InvalidTenantError

if TYPE_CHECKING:
    from hope_country_workspace.security.models import CountryOffice


@pytest.fixture()
def manager():
    return TenantManager()


@pytest.fixture()
def household(afghanistan: "CountryOffice"):
    from testutils.factories import HouseholdFactory

    return HouseholdFactory(country_office=afghanistan)


def test_get_tenant_filter_no_active_tenant(manager):
    from hope_country_workspace.models import Household

    manager.model = Household
    assert manager.get_tenant_filter() == {}


def test_get_tenant_filter_invalid_tenant(manager, afghanistan):
    from hope_country_workspace.models import Household

    manager.model = Household
    with pytest.raises(InvalidTenantError):
        with state.set(must_tenant=True):
            manager.get_tenant_filter()


def test_get_tenant_filter_valid_tenant(manager, afghanistan):
    from hope_country_workspace.models import Household

    manager.model = Household
    with state.set(must_tenant=True, tenant=afghanistan):
        assert manager.get_tenant_filter() == {"country_office": afghanistan}


def test_get_tenant_filter_invalid_model(manager, afghanistan):
    from hope_country_workspace.models import Household

    manager.model = Household
    with mock.patch(
        "hope_country_workspace.models.Household.Tenant.tenant_filter_field", ""
    ):
        with pytest.raises(ValueError):
            with state.set(must_tenant=True, tenant=afghanistan):
                manager.get_tenant_filter()


def test_get_tenant_filter_all(manager, afghanistan):
    from hope_country_workspace.models import Household

    manager.model = Household
    with mock.patch(
        "hope_country_workspace.models.Household.Tenant.tenant_filter_field", "__all__"
    ):
        with state.set(must_tenant=True, tenant=afghanistan):
            assert manager.get_tenant_filter() == {}


#
#
# def test_get_queryset_active(manager, household: "Household"):
#     from hope_country_workspace.models import Household
#
#     manager.model = Household
#     with state.set(must_tenant=True, tenant=household.business_area):
#         assert manager.get_queryset()
#

#
# def test_get_queryset_not_active(manager, household, country_office):
#     from hope_country_workspace.models import Household
#     manager.model = Household
#     with state.set(must_tenant=True, tenant=country_office):
#         assert not manager.get_queryset()
