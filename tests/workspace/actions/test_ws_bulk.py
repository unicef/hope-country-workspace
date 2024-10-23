import io
from pathlib import Path
from typing import TYPE_CHECKING

from django.urls import reverse

import openpyxl
import pytest
from testutils.factories import DataCheckerFactory, FlexFieldFactory
from testutils.utils import select_office
from webtest import Checkbox, Upload

from country_workspace.constants import HOUSEHOLD_CHECKER_NAME, INDIVIDUAL_CHECKER_NAME
from country_workspace.state import state
from country_workspace.workspaces.admin.actions.bulk_export import TYPES, bulk_update_export_impl

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryHousehold

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


@pytest.fixture()
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    yield co


@pytest.fixture()
def program(office, force_migrated_records):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        household_checker=DataCheckerFactory(name=HOUSEHOLD_CHECKER_NAME),
        individual_checker=DataCheckerFactory(name=INDIVIDUAL_CHECKER_NAME),
        household_columns="__str__\nid\nxx",
        individual_columns="__str__\nid\nxx",
    )


@pytest.fixture()
def household(program):
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory(
        batch__program=program, batch__country_office=program.country_office, flex_fields={"size": 5}
    )


@pytest.fixture()
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    yield django_app


@pytest.mark.parametrize("field, validator", list(TYPES.items()))
def test_validator(field, validator):
    flex_field = FlexFieldFactory(field__field_type=field, field__attrs={"choices": [("a", "A")]})
    assert validator(flex_field)()


def test_bulk_update_export_impl(household: "CountryHousehold", force_migrated_records):
    FIELDS = [
        "id",
        "gender",
        "given_name",
        "role",
        "relationship",
        "first_registration_date",
        "birth_date",
        "disability",
    ]
    ret = bulk_update_export_impl(
        household.members.all(),
        household.batch.program,
        {"fields": FIELDS},
    )
    workbook = openpyxl.load_workbook(io.BytesIO(ret.getvalue()))
    sheet = workbook.worksheets[0]
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    assert headers == FIELDS
    # with Path("AAAAAAA.xlsx").open("bw") as f:
    #     f.write(ret.getvalue())


def test_bulk_update_export(app: "DjangoTestApp", force_migrated_records, household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    FIELDS = [
        "birth_date",
        "disability",
        "first_registration_date",
        "gender",
        "given_name",
        "relationship",
        "role",
    ]
    with select_office(app, household.country_office):
        res = app.get(f"{url}?batch__program__exact={household.batch.program.pk}")
        form = res.forms["changelist-form"]
        form["action"] = "bulk_update_export"
        form.set("_selected_action", True, 0)
        res = form.submit()

        form = res.forms["bulk-update-form"]
        for i in range(len(form.fields.get("fields"))):
            target: Checkbox = form.fields.get("fields")[i]
            if target._value in FIELDS:
                target.checked = True
        res = form.submit("_export")

        assert res.status_code == 200
        assert res.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        workbook = openpyxl.load_workbook(io.BytesIO(res.content))
        sheet = workbook.worksheets[0]
        headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        assert headers == ["id"] + FIELDS


@pytest.mark.xfail()
def test_bulk_update_import(app: "DjangoTestApp", force_migrated_records, household: "CountryHousehold") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, household.country_office):
        data = Path(__file__).parent / "ind_updates.xlsx"
        res = app.get(f"{url}?batch__program__exact={household.batch.program.pk}")
        res = res.click("Import File Updates")
        res.forms["bulk-update-form"]["file"] = Upload(data.name, data.read_bytes())
        res = res.forms["bulk-update-form"].submit("_import")
        assert False
