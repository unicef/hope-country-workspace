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
        household_checker=individual_checker,
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


def test_regex_update_impl(household):
    from country_workspace.models import Household

    regex_update_impl(Household.objects.all(), {"field": "full_name", "regex": ".*", "subst": "__NEW VALUE__"})

    household.refresh_from_db()
    assert household.flex_fields["full_name"] == "__NEW VALUE__"


def test_regex_update(app: "DjangoTestApp", force_migrated_records, household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    with select_office(app, household.country_office, household.program):
        res = app.get(url)
        form = res.forms["changelist-form"]
        form["action"] = "regex_update"
        form.set("_selected_action", True)
        res = form.submit()
        form = res.forms["regex-update-form"]
        form["field"].select(text="Full Name")
        form["regex"] = ".*"
        form["subst"] = "__NEW VALUE__"
        res = form.submit("_preview")

        form = res.forms["regex-update-form"]
        form.submit("_apply")

        household.refresh_from_db()
        assert household.flex_fields["full_name"] == "__NEW VALUE__"
