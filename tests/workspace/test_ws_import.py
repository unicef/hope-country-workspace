import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import responses
from constance import config
from constance.test import override_config
from django.urls import reverse
from webtest import Upload, forms

from country_workspace.state import state
from country_workspace.contrib.aurora.exceptions import TooManyBeneficiaryError
from tests.contrib.aurora import stub

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram


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
    if program.beneficiary_group.master_detail:
        res.forms["import-file"]["rdi-detail_column_label"] = "household_id"
    else:
        res.forms["import-file"]["rdi-people_column_prefix"] = "pp_"

    res = res.forms["import-file"].submit()

    assert res.status_code == 302
    if program.beneficiary_group.master_detail:
        assert program.households.count() == 1
        assert program.individuals.count() == 5
        hh: "CountryHousehold" = program.households.first()
        assert hh.members.count() == 5
        assert (head := hh.heads().first())
        assert head.name == "Edward Jeffrey Rogers"
    else:
        assert program.households.count() == 0
        assert program.individuals.count() == 4
        for individual in program.individuals.all():
            assert individual.household is None
        ind: "CountryIndividual" = program.individuals.first()
        assert ind.name == "Collector ForJanIndex_3"


@pytest.fixture
def form_aurora(
    app: "DjangoTestApp", program: "CountryProgram", mocked_responses: responses.RequestsMock, stub_data: dict[str, Any]
) -> forms.Form:
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

    return res.forms["import-aurora"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("stub_data", "hh_count", "ind_count"),
    [
        (stub.imported["no_individuals"], 0, 0),
        (stub.imported["empty_household_data"], 1, 1),
        (stub.imported["update_head_name"], 1, 1),
    ],
    ids=[
        "no_individuals",
        "empty_household_data",
        "update_head_name",
    ],
)
@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_import_data_aurora_success(
    force_migrated_records: None,
    program: "CountryProgram",
    form_aurora: forms.Form,
    stub_data: dict[str, Any],
    hh_count: int,
    ind_count: int,
) -> None:
    form_aurora.submit()

    master_detail = program.beneficiary_group.master_detail
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("stub_data", "hh_count", "ind_count", "error_type", "error_message"),
    [
        (
            stub.imported["correct"],
            2,
            3,
            TooManyBeneficiaryError,
            r"Expected one Individual for record 6, but got 2",
        ),
        (
            stub.imported["multiple_households"],
            0,
            1,
            TooManyBeneficiaryError,
            r"Expected one Household for record 8, but got 2",
        ),
        (
            stub.imported["invalid_key"],
            0,
            0,
            ValueError,
            r".*must contain an underscore",
        ),
        (
            stub.imported["multiple_individuals_if_not_hh"],
            1,
            2,
            TooManyBeneficiaryError,
            r"Expected one Individual for record 12, but got 2",
        ),
        (
            stub.imported["invalid_record_id"],
            0,
            0,
            ValueError,
            r"Invalid or missing record ID: None",
        ),
    ],
    ids=(
        "correct_multiple_individuals",
        "multiple_households",
        "invalid_key",
        "multiple_individuals_if_not_hh",
        "invalid_record_id",
    ),
)
@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_import_data_aurora_errors(
    force_migrated_records: None,
    program: "CountryProgram",
    form_aurora: forms.Form,
    stub_data: dict[str, Any],
    hh_count: int,
    ind_count: int,
    error_type: type[Exception],
    error_message: str,
) -> None:
    master_detail = program.beneficiary_group.master_detail
    expected_success = (
        (stub_data == stub.imported["multiple_households"] and not master_detail)
        or (stub_data == stub.imported["multiple_individuals_if_not_hh"] and master_detail)
        or (stub_data == stub.imported["correct"] and master_detail)
    )

    if expected_success:
        form_aurora.submit()
        assert program.individuals.count() == ind_count
        assert program.households.count() == (hh_count if master_detail else 0)
    else:
        with pytest.raises(error_type, match=error_message):
            form_aurora.submit()
