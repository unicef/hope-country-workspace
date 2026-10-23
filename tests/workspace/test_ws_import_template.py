from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.urls import reverse
from hope_flex_fields.models import DataChecker
from openpyxl import Workbook, load_workbook
from webtest import Upload

from country_workspace.contrib.hope.constants import PEOPLE_CHECKER_NAME
from country_workspace.models import Batch
from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp

    from country_workspace.models import Office
    from country_workspace.workspaces.models import CountryProgram

pytestmark = pytest.mark.django_db


@pytest.fixture
def office() -> "Office":
    from testutils.factories import OfficeFactory

    office = OfficeFactory()
    state.tenant = office
    return office


@pytest.fixture
def app(django_app_factory) -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    django_app.set_user(SuperUserFactory(username="superuser"))
    return django_app


@pytest.fixture
def md_program(office, force_migrated_records, household_checker, individual_checker) -> "CountryProgram":
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        beneficiary_group__master_detail=True,
    )


@pytest.fixture
def people_program(office, force_migrated_records) -> "CountryProgram":
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=None,
        individual_checker=DataChecker.objects.get(name=PEOPLE_CHECKER_NAME),
        beneficiary_group__master_detail=False,
    )


def download_template(app: "DjangoTestApp", program: "CountryProgram") -> Workbook:
    res = app.get("/").follow()
    res.forms["select-tenant"]["tenant"] = program.country_office.pk
    res.forms["select-tenant"].submit()
    res = app.get(reverse("workspace:workspaces_countryprogram_export_import_template", args=[program.pk]))
    return load_workbook(BytesIO(res.body))


def fill(sheet, values: dict[str, object]) -> None:
    headers = [cell.value for cell in sheet[1]]
    assert set(values) <= set(headers), set(values) - set(headers)
    sheet.append([values.get(header) for header in headers])


def upload(app: "DjangoTestApp", program: "CountryProgram", workbook: Workbook) -> None:
    out = BytesIO()
    workbook.save(out)
    res = app.get(reverse("workspace:workspaces_countryprogram_import_data", args=[program.pk]))
    form = res.forms["import-file"]
    form["_selected_tab"] = "rdi"
    form["rdi-file"] = Upload("filled_template.xlsx", out.getvalue())
    form["rdi-validate_after_import"] = False
    with patch("country_workspace.contrib.hope.beneficiary_reference._resolve_hh_batch_pks") as resolve:
        resolve.side_effect = lambda: (None, Batch.objects.last().pk)
        res = form.submit()
    assert res.status_code == 302


def test_master_detail_template_imports_without_touching_the_form_defaults(
    app: "DjangoTestApp", md_program: "CountryProgram"
) -> None:
    workbook = download_template(app, md_program)
    assert [ws.title for ws in workbook.worksheets if ws.sheet_state == "visible"] == ["Households", "Individuals"]
    fill(workbook["Households"], {"household_id": 1, "size": 2, "head_of_household_id": 1})
    fill(workbook["Individuals"], {"individual_id": 1, "household_id": 1, "full_name": "Jeff Rogers"})
    fill(workbook["Individuals"], {"individual_id": 2, "household_id": 1, "full_name": "Ann Rogers"})

    upload(app, md_program, workbook)

    assert md_program.households.count() == 1
    assert md_program.individuals.count() == 2
    household = md_program.households.get()
    assert household.members.count() == 2
    assert md_program.individuals.get(pk=household.head).name == "Jeff Rogers"


def test_people_template_imports_without_touching_the_form_defaults(
    app: "DjangoTestApp", people_program: "CountryProgram"
) -> None:
    workbook = download_template(app, people_program)
    assert [ws.title for ws in workbook.worksheets if ws.sheet_state == "visible"] == ["People"]
    fill(workbook["People"], {"pp_index_id": 1, "pp_full_name": "Jane Doe"})
    fill(workbook["People"], {"pp_index_id": 2, "pp_full_name": "John Doe"})

    upload(app, people_program, workbook)

    assert people_program.households.count() == 0
    assert sorted(people_program.individuals.values_list("name", flat=True)) == ["Jane Doe", "John Doe"]
