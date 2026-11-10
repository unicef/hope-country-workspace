from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.conf import LazySettings

from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from responses import RequestsMock

    from country_workspace.workspaces.models import CountryHousehold, CountryProgram


pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office):
    from testutils.factories import CountryProgramFactory, DataCheckerFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=DataCheckerFactory(fields=["consent"]),
        individual_checker=DataCheckerFactory(fields=["gender", "national_passport_document_number"]),
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)


@pytest.fixture
def app(
    django_app_factory: "MixinWithInstanceVariables",
    mocked_responses: "RequestsMock",
    settings: LazySettings,
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.mark.parametrize(
    ("master_detail", "should_be_visible"),
    [
        (True, True),
        (False, False),
    ],
    ids=["visible", "hidden"],
)
def test_configure_hh_columns(app, household: "CountryHousehold", master_detail: bool, should_be_visible: bool):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = master_detail
    program.beneficiary_group.save()

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        doc = res.pyquery

        # Menu rendered by @choice household_group
        menu_el = doc("details[name='household_group']")

        if should_be_visible:
            # 1) Menu must be present when master_detail=True
            assert menu_el, "household_group choice menu must be rendered when master_detail=True"

            options = list(menu_el.find(".choice-menu-list a").items())
            assert options, "household_group menu must have items"

            # 2) The menu button must display group_label
            assert menu_el.find("summary").text().strip() == program.beneficiary_group.group_label

            # 3) Collect links of all items
            option_values: set[str] = set()
            for opt in options:
                value = opt.attr("href")
                if value:
                    option_values.add(value)

            # 4) Ensure options contain links to *_columns and *_defaults views
            assert reverse("workspace:workspaces_countryprogram_household_columns", args=[program.pk]) in option_values
            assert reverse("workspace:workspaces_countryprogram_household_defaults", args=[program.pk]) in option_values

            # 5) Configure columns via household_columns view
            url = reverse("workspace:workspaces_countryprogram_household_columns", args=[program.pk])
            res = app.get(url)
            form = res.forms["configure-columns"]
            form["columns"] = ["name", "flex_fields__consent"]
            form.submit().follow()

            program.refresh_from_db()
            assert program.household_columns == "name\nflex_fields__consent"

            # 6) Verify household changelist rendering
            hh_list = reverse("workspace:workspaces_countryhousehold_changelist")
            res = app.get(hh_list)
            # Internal field name must not be visible
            assert not res.pyquery("div.text a:contains('flex_fields__consent')")
            # Human-readable label from checker must be visible
            assert res.pyquery("div.text a:contains('Consent')")
        else:
            # When master_detail=False, the menu must not be rendered
            assert not menu_el, "household_group choice menu must NOT be rendered when master_detail=False"


def test_configure_ind_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        doc = res.pyquery

        # Menu rendered by @choice individual_group
        menu_el = doc("details[name='individual_group']")
        assert menu_el, "individual_group choice menu must be rendered"

        options = list(menu_el.find(".choice-menu-list a").items())
        assert options, "individual_group menu must have items"

        # 1) The menu button must display member_label
        assert menu_el.find("summary").text().strip() == program.beneficiary_group.member_label

        # 2) Collect links of all items
        option_values: set[str] = set()
        for opt in options:
            value = opt.attr("href")
            if value:
                option_values.add(value)

        # 3) Ensure options contain links to *_columns and *_defaults views
        assert reverse("workspace:workspaces_countryprogram_individual_columns", args=[program.pk]) in option_values
        assert reverse("workspace:workspaces_countryprogram_individual_defaults", args=[program.pk]) in option_values

        # 4) Configure columns via individual_columns view
        url = reverse("workspace:workspaces_countryprogram_individual_columns", args=[program.pk])
        res = app.get(url)
        form = res.forms["configure-columns"]
        form["columns"] = ["name", "flex_fields__gender", "flex_fields__national_passport_document_number"]
        form.submit().follow()

        program.refresh_from_db()
        lines = program.individual_columns.splitlines()
        assert len(lines) == 3
        assert set(lines) == {
            "name",
            "flex_fields__gender",
            "flex_fields__national_passport_document_number",
        }

        # 5) Individual changelist must display configured columns
        ind_list = reverse("workspace:workspaces_countryindividual_changelist")
        res = app.get(ind_list)
        assert "gender" in res.text
        assert "national_passport_document_number" in res.text


def test_household_alien_fields_to_ignore_in_choice_dropdown(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        doc = res.pyquery

        menu_el = doc("details[name='household_group']")
        assert menu_el

        option_values = {a.attr("href") for a in menu_el.find(".choice-menu-list a").items()}
        expected_url = reverse(
            "workspace:workspaces_countryprogram_household_alien_fields_to_ignore", args=[program.pk]
        )
        assert expected_url in option_values


def test_individual_alien_fields_to_ignore_in_choice_dropdown(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        doc = res.pyquery

        menu_el = doc("details[name='individual_group']")
        assert menu_el

        option_values = {a.attr("href") for a in menu_el.find(".choice-menu-list a").items()}
        expected_url = reverse(
            "workspace:workspaces_countryprogram_individual_alien_fields_to_ignore", args=[program.pk]
        )
        assert expected_url in option_values


def test_configure_household_alien_fields_to_ignore_add_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.hh_alien_columns_to_ignore = None
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_household_alien_fields_to_ignore", args=[program.pk])
        res = app.get(url)
        assert res.status_code == 200

        res = app.post(url, {"new_columns": ["alien_field_1", "alien_field_2"]})
        assert res.status_code == 302

        program.refresh_from_db()
        assert program.hh_alien_columns_to_ignore is not None
        columns = program.hh_alien_columns_to_ignore.splitlines()
        assert set(columns) == {"alien_field_1", "alien_field_2"}


def test_configure_household_alien_fields_to_ignore_remove_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.hh_alien_columns_to_ignore = "existing_field_1\nexisting_field_2\nexisting_field_3"
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_household_alien_fields_to_ignore", args=[program.pk])
        res = app.get(url)
        assert res.status_code == 200

        res = app.post(url, {"remove_columns": ["existing_field_2"]})
        assert res.status_code == 302

        program.refresh_from_db()
        columns = program.hh_alien_columns_to_ignore.splitlines()
        assert set(columns) == {"existing_field_1", "existing_field_3"}


def test_configure_household_alien_fields_to_ignore_add_and_remove(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.hh_alien_columns_to_ignore = "keep_this\nremove_this"
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_household_alien_fields_to_ignore", args=[program.pk])

        res = app.post(
            url,
            {
                "remove_columns": ["remove_this"],
                "new_columns": ["new_field"],
            },
        )
        assert res.status_code == 302

        program.refresh_from_db()
        columns = program.hh_alien_columns_to_ignore.splitlines()
        assert set(columns) == {"keep_this", "new_field"}


def test_configure_individual_alien_fields_to_ignore_add_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.ind_alien_columns_to_ignore = None
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_individual_alien_fields_to_ignore", args=[program.pk])
        res = app.get(url)
        assert res.status_code == 200

        res = app.post(url, {"new_columns": ["ind_alien_1", "ind_alien_2"]})
        assert res.status_code == 302

        program.refresh_from_db()
        assert program.ind_alien_columns_to_ignore is not None
        columns = program.ind_alien_columns_to_ignore.splitlines()
        assert set(columns) == {"ind_alien_1", "ind_alien_2"}


def test_configure_individual_alien_fields_to_ignore_remove_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.ind_alien_columns_to_ignore = "ind_existing_1\nind_existing_2\nind_existing_3"
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_individual_alien_fields_to_ignore", args=[program.pk])

        res = app.post(url, {"remove_columns": ["ind_existing_1", "ind_existing_3"]})
        assert res.status_code == 302

        program.refresh_from_db()
        columns = program.ind_alien_columns_to_ignore.splitlines()
        assert columns == ["ind_existing_2"]


def test_configure_individual_alien_fields_to_ignore_add_and_remove(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.ind_alien_columns_to_ignore = "keep_ind\nremove_ind"
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_individual_alien_fields_to_ignore", args=[program.pk])

        res = app.post(
            url,
            {
                "remove_columns": ["remove_ind"],
                "new_columns": ["new_ind_field"],
            },
        )
        assert res.status_code == 302

        program.refresh_from_db()
        columns = program.ind_alien_columns_to_ignore.splitlines()
        assert set(columns) == {"keep_ind", "new_ind_field"}


def test_configure_alien_fields_removes_all_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.hh_alien_columns_to_ignore = "only_field"
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_household_alien_fields_to_ignore", args=[program.pk])

        res = app.post(url, {"remove_columns": ["only_field"]})
        assert res.status_code == 302

        program.refresh_from_db()
        assert program.hh_alien_columns_to_ignore is None


def test_configure_alien_fields_no_duplicates(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save()
    program.hh_alien_columns_to_ignore = "existing_field"
    program.save()

    with select_office(app, program.country_office, program):
        url = reverse("workspace:workspaces_countryprogram_household_alien_fields_to_ignore", args=[program.pk])

        res = app.post(url, {"new_columns": ["existing_field", "new_field"]})
        assert res.status_code == 302

        program.refresh_from_db()
        columns = program.hh_alien_columns_to_ignore.splitlines()
        assert len(columns) == 2
        assert set(columns) == {"existing_field", "new_field"}


def test_household_alien_fields_not_visible_when_master_detail_false(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program
    program.beneficiary_group.master_detail = False
    program.beneficiary_group.save()

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        doc = res.pyquery

        menu_el = doc("details[name='household_group']")
        assert not menu_el


def test_user_menu_links_office_and_programme_admin(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())

    links = {a.text.strip(): a.attrib["href"] for a in res.pyquery("#user-menu .user-menu-list a")}
    assert links["Office in Admin"] == reverse(
        "admin:country_workspace_office_change", args=[program.country_office.pk]
    )
    assert links["Programme in Admin"] == reverse("admin:country_workspace_program_change", args=[program.pk])
