from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper
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
    settings: SettingsWrapper,
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

        # Select rendered by @choice household_group
        select_el = doc("select[name='household_group']")

        if should_be_visible:
            # 1) Select must be present when master_detail=True
            assert select_el, "household_group choice select must be rendered when master_detail=True"

            options = list(select_el.find("option").items())
            assert options, "household_group select must have options"

            # 2) First option must display group_label
            first_text = options[0].text().strip()
            assert first_text == program.beneficiary_group.group_label

            # 3) Collect values of all options
            option_values: set[str] = set()
            for opt in options:
                value = opt.attr("value")
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
            # When master_detail=False, select must not be rendered
            assert not select_el, "household_group choice select must NOT be rendered when master_detail=False"


def test_configure_ind_columns(app, household: "CountryHousehold"):
    program: "CountryProgram" = household.program

    with select_office(app, program.country_office, program):
        res = app.get(program.get_change_url())
        doc = res.pyquery

        # Select rendered by @choice individual_group
        select_el = doc("select[name='individual_group']")
        assert select_el, "individual_group choice select must be rendered"

        options = list(select_el.find("option").items())
        assert options, "individual_group select must have options"

        # 1) First option must display member_label
        first_text = options[0].text().strip()
        assert first_text == program.beneficiary_group.member_label

        # 2) Collect values of all options
        option_values: set[str] = set()
        for opt in options:
            value = opt.attr("value")
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
