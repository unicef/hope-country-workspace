import datetime
from typing import TYPE_CHECKING

import freezegun
import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import SettingsWrapper

    from country_workspace.models import AsyncJob
    from country_workspace.workspaces.models import CountryHousehold


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
        individual_checker=individual_checker,
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program, batch__country_office=program.country_office, flex_fields={"size": 5}
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_ws_validate(
    app: "DjangoTestApp", force_migrated_records, settings: "SettingsWrapper", household: "CountryHousehold"
) -> None:
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with freezegun.freeze_time("2020-01-01 00:00:00"):
        with select_office(app, household.country_office, household.program):
            res = app.get(url)
            form = res.forms["changelist-form"]
            form.set("_selected_action", True)
            form["action"].select("validate_records")
            res = form.submit()
            assert res.status_code == 302

            job: "AsyncJob" = household.program.jobs.first()
            assert job is not None
            household.refresh_from_db()
            assert household.last_checked.date() == datetime.date(2020, 1, 1)
            assert household.errors
