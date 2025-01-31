from pathlib import Path
from typing import TYPE_CHECKING, Any
import responses
import pytest
import re
from django.urls import reverse
from webtest import Upload

from country_workspace.state import state
from constance import config

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


@pytest.fixture
def program(office, force_migrated_records, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory, RegistrationFactory

    program = CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )
    RegistrationFactory.create_batch(3, program=program)

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
    res.forms["import-file"]["rdi-detail_column_label"] = "full_name"
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
    ("stub_data", "error_expected", "error_message"),
    [
        (stub.correct, False, None),
        (stub.without_prefix_household, True, "No data found with prefix"),
        (stub.without_prefix_individuals, True, "No data found with prefix"),
        (stub.multiple_households, True, "Multiple households found"),
        (stub.without_head, True, "No head found"),
    ],
)
def test_import_data_aurora(
    force_migrated_records: None,
    app: "DjangoTestApp",
    program: "CountryProgram",
    mocked_responses: responses.RequestsMock,
    stub_data: dict[str, Any],
    error_expected: bool,
    error_message: str,
) -> None:
    # NOTE: This test is linked to the stub data in `tests/contrib/aurora/stub.py`
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
    res.forms["import-aurora"]["aurora-registration"] = program.registrations.first().pk

    if error_expected:
        with pytest.raises(ValueError, match=error_message):
            res.forms["import-aurora"].submit()
    else:
        res = res.forms["import-aurora"].submit()

        assert len(mocked_responses.calls) > 0
        assert config.AURORA_API_URL in mocked_responses.calls[0].request.url

        households: "list[CountryHousehold]" = program.households.all()
        assert households.count() == 2
        assert {hh.members.count() for hh in households} == {1, 3}
        assert {hh.heads().first().name for hh in households} == {"as", "Oksana"}
        assert {hh.name for hh in households} == {"sad", "Berezinska"}
