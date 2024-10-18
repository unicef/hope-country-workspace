from typing import TYPE_CHECKING

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryHousehold


@pytest.fixture()
def office(db, worker_id):
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    yield co


@pytest.fixture()
def program(office, worker_id):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
        household_checker__name=f"HH Checker {worker_id}",
        individual_checker__name=f"IND Checker  {worker_id}",
    )


@pytest.fixture()
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.mark.selenium
def test_list_household(selenium, user, household: "CountryHousehold"):
    from testutils.perms import user_grant_permissions

    from country_workspace.workspaces.models import CountryHousehold

    selenium.get(f"{selenium.live_server.url}")
    with user_grant_permissions(
        user,
        [
            "workspaces.view_countryhousehold",
            "workspaces.view_countryindividual",
            "workspaces.view_countryprogram",
        ],
        household.program.country_office,
    ):
        # Login
        selenium.find_by_css("input[name=username").send_keys(user.username)
        selenium.find_by_css("input[name=password").send_keys(user._password)
        selenium.find_by_css("input[type=submit").click()
        # Select Tenant
        Select(selenium.wait_for(By.CSS_SELECTOR, "select[name=tenant]")).select_by_visible_text(
            household.program.country_office.name
        )
        selenium.find_by_css("input[type=submit").click()
        selenium.wait_for(By.CSS_SELECTOR, "h1")
        # Workspace
        selenium.wait_for(By.LINK_TEXT, str(CountryHousehold._meta.verbose_name_plural)).click()
        selenium.wait_for_url("/workspaces/countryhousehold/")
        # Household changelist
        assert "Please select a program on the left" in selenium.page_source
        selenium.wait_for(
            By.CSS_SELECTOR,
            "#batch__program__exact_batch__program__isnull .select2-selection.select2-selection--single",
        ).click()
        el = selenium.wait_for(By.CSS_SELECTOR, ".select2-search__field")
        el.send_keys(household.program.name)
        selenium.wait_for(
            By.CSS_SELECTOR,
            "li.select2-results__option.select2-results__option--highlighted",
        ).click()

        selenium.wait_for(By.LINK_TEXT, str(household.name)).click()
        selenium.wait_for_url(household.get_change_url())
        selenium.wait_for(
            By.CSS_SELECTOR,
            "a.closelink",
        ).click()
        selenium.wait_for_url(f"/workspaces/countryhousehold/?batch__program__exact={household.program.pk}")


@pytest.mark.selenium
def test_edit_household(selenium, user, household: "CountryHousehold"):
    from testutils.perms import user_grant_permissions
    from testutils.selenium import force_login

    with user_grant_permissions(
        user,
        [
            "workspaces.view_countryhousehold",
            "workspaces.view_countryindividual",
            "workspaces.view_countryprogram",
            "workspaces.change_countryhousehold",
            "workspaces.change_countryindividual",
            "workspaces.change_countryprogram",
        ],
        household.program.country_office,
    ):
        force_login(selenium, user, household.program.country_office)
        selenium.get(f"{selenium.live_server.url}/workspaces/countryhousehold/")
        assert "Please select a program on the left" in selenium.page_source

        #
        # selenium.wait_for(By.LINK_TEXT, "Close").click()
        # selenium.wait_for(By.CSS_SELECTOR, "h1")
        #
        # selenium.wait_for(
        #     By.CSS_SELECTOR,
        #     "#program__exact_program__isnull .select2-selection.select2-selection--single",
        # ).click()
        # el = selenium.wait_for(By.CSS_SELECTOR, ".select2-search__field")
        # el.send_keys(household.program.name)
        # selenium.wait_for(
        #     By.CSS_SELECTOR,
        #     "li.select2-results__option.select2-results__option--highlighted",
        # ).click()
        # selenium.wait_for_url("/workspaces/countryhousehold/?&program__exact=1")
