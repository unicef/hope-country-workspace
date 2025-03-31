import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import responses
from constance import config
from django.urls import reverse
from webtest import Upload

from country_workspace.state import state
from tests.contrib.aurora import stub

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryHousehold, CountryProgram


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(request, office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory, ProjectFactory, RegistrationFactory

    program = CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
        beneficiary_group__master_detail=request.param,
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


def test_import_data_rdi(force_migrated_records, app, program):
    # NOTE: This test is linked to the content of `data/rdi_one.xlsx`
    res = app.get("/").follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()

    url = reverse("workspace:workspaces_countryprogram_import_data", args=[program.pk])
    data = (Path(__file__).parent.parent / "data/rdi_one.xlsx").read_bytes()

    res = app.get(url)

    res.forms["import-file"]["_selected_tab"] = "rdi"
    res.forms["import-file"]["rdi-file"] = Upload("rdi_one.xlsx", data)
    res.forms["import-file"]["rdi-detail_column_label"] = "full_name_i_c"
    res = res.forms["import-file"].submit()
    assert res.status_code == 302
    assert program.households.count() == 1
    assert program.individuals.count() == 5

    hh: "CountryHousehold" = program.households.first()
    assert hh.members.count() == 5
    assert (head := hh.heads().first())
    assert head.name == "Edward Jeffrey Rogers"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("stub_data", "error_expected", "hh_count", "ind_count", "error_message"),
    [
        (stub.imported["correct"], False, 2, 3, None),  # 2 hh: 1st with 1 ind, 2nd with 2 inds
        (stub.imported["no_individuals"], False, 0, 0, None),  # No individuals
        (stub.imported["multiple_households"], True, 0, 1, "Multiple households found"),  # Multiple households error
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

    master_detail = program.beneficiary_group.master_detail

    if error_expected and master_detail:
        with pytest.raises(ValueError, match=error_message):
            res.forms["import-aurora"].submit()
        return

    res = res.forms["import-aurora"].submit()
    households = program.households.all()
    individuals = program.individuals.all()
    assert individuals.count() == ind_count
    assert households.count() == (hh_count if master_detail else 0)

    if master_detail:
        if hh_count == 2:
            assert {hh.members.count() for hh in households} == {1, 2}
            assert {hh.heads().first().name for hh in households} == {"John", "Jane"}
        elif hh_count == 1 and stub_data == stub.imported["update_head_name"]:
            assert households.first().name == "Doe"
