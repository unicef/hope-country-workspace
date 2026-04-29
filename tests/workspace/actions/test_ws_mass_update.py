from typing import TYPE_CHECKING
import pytest
from django.urls import reverse
from pytest_django.fixtures import SettingsWrapper
from testutils.utils import select_office
from constance.test import override_config
from responses import RequestsMock, matchers

from country_workspace.state import state
from country_workspace.workspaces.admin.cleaners.mass_update import mass_update_impl

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.models import AsyncJob
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
    settings: SettingsWrapper,
) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_mass_update_impl(household):
    from country_workspace.models import Household

    mass_update_impl(Household.objects.all(), {"address": ("djangoformsfieldsfield_set_lambda", "__NEW VALUE__")})

    household.refresh_from_db()
    assert household.flex_fields["address"] == "__NEW VALUE__"


def test_mass_update_impl_empty_queryset():
    from country_workspace.cache.manager import cache_manager
    from country_workspace.models import Household
    from unittest.mock import patch

    with patch.object(cache_manager, "incr_cache_version") as mock_incr:
        mass_update_impl(Household.objects.none(), {"address": ("djangoformsfieldsfield_set_lambda", "x")})
        mock_incr.assert_not_called()


def test_mass_update_impl_create_missing_fields(household):
    from country_workspace.models import Household

    assert "new_field" not in household.flex_fields

    mass_update_impl(
        Household.objects.all(),
        {"new_field": ("djangoformsfieldsfield_set_lambda", "CREATED")},
        create_missing_fields=True,
    )

    household.refresh_from_db()
    assert household.flex_fields["new_field"] == "CREATED"


def test_mass_update_impl_skips_missing_fields_by_default(household):
    from country_workspace.models import Household

    original_fields = dict(household.flex_fields)

    mass_update_impl(
        Household.objects.all(),
        {"nonexistent_field": ("djangoformsfieldsfield_set_lambda", "VALUE")},
    )

    household.refresh_from_db()
    assert "nonexistent_field" not in household.flex_fields
    assert household.flex_fields["address"] == original_fields["address"]


def test_mass_update_impl_bumps_cache(household):
    from country_workspace.cache.manager import cache_manager
    from country_workspace.models import Household

    version_before = cache_manager.get_cache_version(program=household.program)

    mass_update_impl(Household.objects.all(), {"address": ("djangoformsfieldsfield_set_lambda", "X")})

    version_after = cache_manager.get_cache_version(program=household.program)
    assert version_after == version_before + 1


@override_config(HOPE_API_URL="https://hope-dummy.org/api/rest", HOPE_API_TOKEN="dummy_token")
def test_mass_update(app: "DjangoTestApp", household: "CountryHousehold", mocked_responses: RequestsMock) -> None:
    mocked_responses.add(
        method=mocked_responses.GET,
        url="https://hope-dummy.org/api/rest/areas/",
        match=[
            matchers.query_param_matcher(
                {
                    "area_type_area_level": "1",
                    "country_iso_code2": "UA",
                }
            )
        ],
        json={
            "results": [
                {"id": "ua_adm1_kiev", "p_code": "UA-30", "name": "Kyiv City"},
                {"id": "ua_adm1_lviv", "p_code": "UA-46", "name": "Lviv Oblast"},
            ]
        },
        status=200,
    )
    url = reverse("workspace:workspaces_countryhousehold_changelist")
    with select_office(app, household.country_office, household.program):
        res = app.get(url)
        form = res.forms["changelist-form"]
        form["action"] = "mass_update"
        form.set("_selected_action", True)
        res = form.submit()

        form = res.forms["mass-update-form"]
        form["flex_fields__address_0"].select(text="set")
        form["flex_fields__address_1"] = "__NEW VALUE__"
        res = form.submit("_apply")

        job: "AsyncJob" = household.program.jobs.first()
        assert job is not None

        household.refresh_from_db()
        assert household.flex_fields["address"] == "__NEW VALUE__"
