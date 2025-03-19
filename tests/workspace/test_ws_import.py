import re
from typing import TYPE_CHECKING, Any

import pytest
import responses
from constance import config
from django.urls import reverse

from country_workspace.state import state
from tests.contrib.aurora import stub

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryProgram


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory, ProjectFactory, RegistrationFactory

    program = CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )
    project = ProjectFactory(program=program)
    RegistrationFactory.create_batch(3, project=project, active=True)

    return program


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("stub_data", "error_expected", "hh_count", "ind_count", "error_message"),
    [
        (stub.imported["correct"], False, 2, 3, None),  # 2 hh: 1st with 1 ind, 2nd with 2 inds
        (stub.imported["no_individuals"], False, 0, 0, None),  # No individuals, no Household
        (stub.imported["multiple_households"], True, 0, 0, "Multiple households found"),  # Multiple households error
        (stub.imported["empty_household_data"], False, 1, 1, None),  # Only ind without hh data
        (stub.imported["update_head_name"], False, 1, 1, None),  # Household name updated from head
    ],
)
def test_import_data_aurora(
    force_migrated_records: None,
    app: "DjangoTestApp",
    program: "CountryProgram",
    mocked_responses: responses.RequestsMock,
    stub_data: dict[str, Any],
    error_expected: bool,
    hh_count: int,
    ind_count: int,
    error_message: str,
) -> None:
    res = app.get("/").follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()

    url = reverse("workspace:workspaces_countryprogram_import_data", args=[program.pk])

    mocked_responses.add(
        responses.GET,
        re.compile(re.escape(config.AURORA_API_URL) + ".*"),
        json=stub_data,
    )

    res = app.get(url)
    res.forms["import-aurora"]["_selected_tab"] = "aurora"
    res.forms["import-aurora"]["aurora-registration"] = program.projects.registrations.first().pk

    if error_expected:
        with pytest.raises(ValueError, match=error_message):
            res.forms["import-aurora"].submit()
    else:
        res = res.forms["import-aurora"].submit()
        households = program.households.all()
        assert households.count() == hh_count
        assert sum(hh.members.count() for hh in households) == ind_count
        if hh_count == 2:
            assert {hh.members.count() for hh in households} == {1, 2}
            assert {hh.heads().first().name for hh in households} == {"John", "Jane"}
        elif hh_count == 1 and stub_data == stub.imported["update_head_name"]:
            assert households.first().name == "Doe"
