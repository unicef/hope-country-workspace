from typing import TYPE_CHECKING

import pytest
from django.conf import settings

from hope_country_workspace.state import state

if TYPE_CHECKING:
    from hope_country_workspace.security.models import CountryOffice


@pytest.fixture()
def data():
    from testutils.factories import CountryOfficeFactory, HouseholdFactory, UserFactory, UserRoleFactory

    with state.set(must_tenant=False):
        co1: "CountryOffice" = CountryOfficeFactory(name="Afghanistan")
        co2: "CountryOffice" = CountryOfficeFactory(name="Niger")
        co3: "CountryOffice" = CountryOfficeFactory(name="Sudan")

        HouseholdFactory(country_office=co1)
        HouseholdFactory(country_office=co1)
        HouseholdFactory(country_office=co2)
        HouseholdFactory(country_office=co2)

        user = UserFactory(username="user", is_staff=False, is_superuser=False, is_active=True)
        UserRoleFactory(country_office=co1, group__name=settings.ANALYST_GROUP_NAME, user=user)

    return {"Afghanistan": co1, "Niger": co2, "Sudan": co3}


@pytest.mark.parametrize("co,expected", [("Afghanistan", 2), ("Niger", 2), ("Sudan", 0)])
def test_filtering(data, co, expected):
    from hope_country_workspace.models import Household

    assert Household.objects.count() == 4
    with state.set(tenant=data[co], must_tenant=True):
        assert Household.objects.count() == expected
