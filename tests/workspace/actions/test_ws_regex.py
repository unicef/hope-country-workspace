from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state
from country_workspace.workspaces.admin.cleaners.regex import regex_update_impl

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryHousehold

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


FIELD_TEXT = "Address"
FIELD = FIELD_TEXT.lower()
NEW_VALUE = "__NEW VALUE__"
ANYTHING = ".*"


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
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
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_update_json_does_not_change_non_string_values() -> None:
    json = {FIELD: 42}
    original_value = 42

    result = update_json(json, FIELD, re.compile(ANYTHING), NEW_VALUE)

    assert result.original == original_value
    assert result.updated == original_value


def test_update_json_does_not_change_float_values() -> None:
    json = {FIELD: 42.5}
    original_value = 42.5

    result = update_json(json, FIELD, re.compile(ANYTHING), NEW_VALUE)

    assert result.original == original_value
    assert result.updated == original_value
    assert result.original_data_type == "float"
    assert result.updated_data_type == "float"


def test_regex_update_impl(household: "CountryHousehold") -> None:
    from country_workspace.models import Household

    original_checksum = household.checksum
    assert household.flex_fields.get(FIELD) != NEW_VALUE

    regex_update_impl(Household.objects.all(), {"field": FIELD, "regex": ANYTHING, "subst": NEW_VALUE})

    household.refresh_from_db()
    assert household.flex_fields[FIELD] == NEW_VALUE
    assert household.checksum != original_checksum


def test_regex_update(app: "DjangoTestApp", force_migrated_records, household: "CountryHousehold") -> None:
    original_checksum = household.checksum
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    with select_office(app, household.country_office, household.program):
        res = app.get(url)
        form = res.forms["changelist-form"]
        form["action"] = "regex_update"
        form.set("_selected_action", True)
        res = form.submit()
        form = res.forms["regex-update-form"]
        form["field"].select(text=FIELD_TEXT)
        form["regex"] = ANYTHING
        form["subst"] = NEW_VALUE
        res = form.submit("_preview")

        form = res.forms["regex-update-form"]
        form.submit("_apply")

        household.refresh_from_db()
        assert household.flex_fields[FIELD] == NEW_VALUE
        assert household.checksum != original_checksum
