import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import responses
from constance.test import override_config
from django.urls import reverse
from strategy_field.utils import fqn
from webtest import Upload, forms
from django import forms as django_forms

from country_workspace.contrib.hope.constants import PEOPLE_CHECKER_NAME
from country_workspace.models import AsyncJob, Office, Individual, Household, Batch
from country_workspace.state import state
from tests.contrib.aurora import stub
from tests.extras.testutils.factories import DataCheckerFactory

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.models import Office
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram


@pytest.fixture
def office() -> "Office":
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(autouse=True)
def create_cuntries() -> None:
    from testutils.factories import CountryFactory

    countries_to_create = (("af", "AFG", "Afghanistan"), ("IM", "IMN", "Isle of Man"))
    for iso_code2, iso_code3, name in countries_to_create:
        CountryFactory.create(
            iso_code2=iso_code2.upper(),
            iso_code3=iso_code3.upper(),
            name=name,
        )


def get_people_checker() -> "DataCheckerFactory":
    return DataCheckerFactory(
        name=PEOPLE_CHECKER_NAME,
        fields=[
            ("index_id", fqn(django_forms.CharField)),
            ("gender", fqn(django_forms.CharField)),
        ],
    )


def _ff_relationship(required: bool = True) -> None:
    from hope_flex_fields.models import FlexField

    ff_relationship = FlexField.objects.filter(
        name="relationship",
    ).first()
    ff_relationship.attrs = {
        "label": "Relationship",
        "choices": [
            ["BROTHER_SISTER", "Brother / Sister"],
            ["GRANDDAUGHER_GRANDSON", "Granddaughter / Grandson"],
            ["MOTHER_FATHER", "Mother / Father"],
            ["MOTHERINLAW_FATHERINLAW", "Mother-in-law / Father-in-law"],
            ["SISTERINLAW_BROTHERINLAW", "Sister-in-law / Brother-in-law"],
            ["SON_DAUGHTER", "Son / Daughter"],
            ["HEAD", "Head of household (self)"],
        ],
        "required": required,
    }
    ff_relationship.save()


@pytest.fixture
def ff_relationship() -> None:
    _ff_relationship()


@pytest.fixture
def ff_relationship_not_required() -> None:
    _ff_relationship(required=False)


@pytest.fixture
def ff_sex() -> None:
    from hope_flex_fields.models import FlexField

    ff_sex = FlexField.objects.filter(name="sex").first()
    ff_sex.attrs = {
        "choices": [
            ["MALE", "Male"],
            ["FEMALE", "Female"],
        ],
        "required": False,
        "help_text": "",
    }
    ff_sex.save()


@pytest.fixture
def ff_residence_status() -> None:
    from hope_flex_fields.models import FlexField

    ff_residence_status = FlexField.objects.filter(name="residence_status")
    ff_residence_status.update(
        attrs={
            "choices": [
                ["", "None"],
                ["IDP", "Displaced  |  Internally Displaced People"],
                ["REFUGEE", "Displaced  |  Refugee / Asylum Seeker"],
                ["OTHERS_OF_CONCERN", "Displaced  |  Others of Concern"],
                ["HOST", "Non-displaced  |   Host"],
                ["NON_HOST", "Non-displaced  |   Non-host"],
                ["RETURNEE", "Displaced  |   Returnee"],
            ],
            "required": False,
            "help_text": "",
        }
    )


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def program(
    request: pytest.FixtureRequest,
    office: "Office",
    force_migrated_records: None,
    household_checker: "DataChecker",
    individual_checker: "DataChecker",
) -> "CountryProgram":
    from testutils.factories import CountryProgramFactory, ProjectFactory, RegistrationFactory, MappingImporterFactory

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

    MappingImporterFactory(
        office=program.country_office,
        data_checker=program.get_checker_for(Individual),
        rules="gender=sex\nage=birth_year",
    )
    if request.param:
        MappingImporterFactory(
            office=program.country_office,
            data_checker=program.get_checker_for(Household),
            rules="\n".join(  # noqa: FLY002
                [
                    "members_count=count",
                    "head_of_household_id=head_of_household",
                    "primary_collector_id=primary_collector",
                    "alternate_collector_id=alternate_collector",
                    "",
                ]
            ),
        )

    return program


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


@pytest.fixture
def reference_field_names() -> tuple:
    return (
        "head_of_household",
        "primary_collector",
        "alternate_collector",
    )


@pytest.fixture
def form_import_rdi(app: "DjangoTestApp", program: "CountryProgram") -> forms.Form:
    # NOTE: This fixture is linked to the content of `data/rdi_correct.xlsx`
    res = app.get("/").follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()

    url = reverse("workspace:workspaces_countryprogram_import_data", args=[program.pk])
    data = (Path(__file__).parent.parent / "data/rdi_correct.xlsx").read_bytes()
    res = app.get(url)

    res.forms["import-file"]["_selected_tab"] = "rdi"
    res.forms["import-file"]["rdi-file"] = Upload("rdi_correct.xlsx", data)

    return res.forms["import-file"]


def _test_import_rdi_hh_and_individuals(
    form_import_rdi: forms.Form,
    program: "CountryProgram",
    reference_field_names: tuple,
):
    if not program.beneficiary_group.master_detail:
        pytest.skip("Test requires master_detail=True")

    form_import_rdi["rdi-household_id_column"] = "household_id"
    res = form_import_rdi.submit()

    assert res.status_code == 302
    assert program.households.count() == 2
    assert program.individuals.count() == 9

    hh: "CountryHousehold" = program.households.first()
    assert hh.members.count() == 5
    assert (head := program.individuals.get(pk=hh.head))
    assert head.name == "Jeff David Rogers"
    assert "members_count" not in hh.flex_fields
    assert "count" not in hh.flex_fields

    for household in program.households.all():
        for field in reference_field_names:
            assert field in household.flex_fields

    individual = program.individuals.first()
    assert "age" not in individual.flex_fields
    assert "birth_year" not in individual.flex_fields
    assert "gender" not in individual.flex_fields
    assert "sex" in individual.flex_fields


@pytest.mark.django_db
def test_import_rdi_hh_and_individuals_no_validation(
    force_migrated_records,
    app,
    program,
    ff_relationship,
    ff_sex,
    form_import_rdi,
    reference_field_names,
):
    with patch("country_workspace.contrib.hope.beneficiary_reference._resolve_hh_batch_pks") as mock_resolve:
        mock_resolve.side_effect = lambda: (None, Batch.objects.last().pk)
        _test_import_rdi_hh_and_individuals(form_import_rdi, program, reference_field_names)


def _test_import_rdi_people_only(
    program: "CountryProgram",
    form_import_rdi: forms.Form,
) -> None:
    if program.beneficiary_group.master_detail:
        pytest.skip("Test requires master_detail=False")

    form_import_rdi["rdi-people_prefix"] = "pp_"
    res = form_import_rdi.submit()

    assert res.status_code == 302
    assert program.households.count() == 0
    assert program.individuals.count() == 4
    for individual in program.individuals.all():
        assert individual.household is None
    individual: "CountryIndividual" = program.individuals.first()
    assert individual.name == "Collector ForJanIndex_3"
    assert "age" not in individual.flex_fields
    assert "birth_year" not in individual.flex_fields
    assert "sex" in individual.flex_fields


def test_import_rdi_people_only_with_no_validation(
    force_migrated_records: None,
    app: "DjangoTestApp",
    program: "CountryProgram",
    ff_sex: None,
    form_import_rdi: forms.Form,
) -> None:
    program.individual_checker = get_people_checker()
    program.save()

    with patch("country_workspace.contrib.hope.beneficiary_reference._resolve_hh_batch_pks") as mock_resolve:
        mock_resolve.side_effect = lambda: (None, Batch.objects.last().pk)
        _test_import_rdi_people_only(program=program, form_import_rdi=form_import_rdi)


@pytest.fixture
@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def form_aurora(
    app: "DjangoTestApp", program: "CountryProgram", mocked_responses: responses.RequestsMock, stub_data: dict[str, Any]
) -> forms.Form:
    res = app.get("/").follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()

    url = reverse("workspace:workspaces_countryprogram_import_data", args=[program.pk])

    mocked_responses.add(
        responses.GET,
        re.compile(r"https://hope-dummy\.org/api/.*"),
        json=stub_data,
    )

    res = app.get(url)
    res.forms["import-aurora"]["_selected_tab"] = "aurora"
    res.forms["import-aurora"]["aurora-validate_after_import"] = False  # Or True
    res.forms["import-aurora"]["aurora-registration"] = program.projects.registrations.first().pk

    return res.forms["import-aurora"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("stub_data", "expected_people"),
    [
        (stub.imported["no_results"], 0),
        (stub.imported["two_results"], 2),
    ],
    ids=[
        "no_results",
        "two_results",
    ],
)
@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest/", AURORA_API_TOKEN="dummy_token")
def test_import_data_aurora_success(
    force_migrated_records: None,
    program: "CountryProgram",
    form_aurora: forms.Form,
    stub_data: dict[str, Any],
    expected_people: int,
) -> None:
    assert program.individuals.count() == 0
    assert program.households.count() == 0

    res = form_aurora.submit()

    assert res.status_code in (200, 302)
    # Aurora import is queued; run the job so created individuals/households are visible
    job = AsyncJob.objects.filter(program=program).order_by("-id").first()
    if job:
        job.execute()
    program.refresh_from_db()
    if program.beneficiary_group.master_detail:
        assert program.individuals.count() == expected_people
        assert program.households.count() == 0
    else:
        assert program.individuals.count() == expected_people
        assert program.households.count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "stub_data",
    [stub.imported["invalid_pk"]],
    ids=["invalid_pk"],
)
@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest/", AURORA_API_TOKEN="dummy_token")
def test_import_data_aurora_failure(
    force_migrated_records: None,
    program: "CountryProgram",
    form_aurora: forms.Form,
    stub_data: dict[str, Any],
) -> None:
    with pytest.raises(ImportError, match=r"Last successful record ID|Missing record pk"):
        form_aurora.submit()

    assert program.individuals.count() == 0
    assert program.households.count() == 0
