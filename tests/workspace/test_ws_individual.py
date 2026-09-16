from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryIndividual

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]

PHOTO = b"\x89PNG\r\n\x1a\nphoto"


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def individual(program):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(
        household__batch__program=program, household__batch__country_office=program.country_office
    )


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_ind_change(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)
        assert res.status_code == 200, res.location
        res = res.forms["countryindividual_form"].submit()
        assert res.status_code == 302, res.location


def test_ind_validate(app: "DjangoTestApp", force_migrated_records, individual: "CountryIndividual") -> None:
    individual.flex_fields = {}
    individual.save()
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)
        assert res.status_code == 200
        res = res.click("Validate").follow()
        assert res.status_code == 200
        individual.refresh_from_db()
        assert individual.errors


@pytest.fixture
def other_program(office, household_checker, individual_checker):
    """A second program, to check that images are scoped to the selected one."""
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
    )


@pytest.fixture
def photo_url(individual: "CountryIndividual") -> str:
    """The url serving a photo stored for the individual."""
    from country_workspace.models.flex_file import FlexFieldFile
    from country_workspace.utils.flex_files import write_flex_file

    reference = write_flex_file(individual, "photo", PHOTO, "image/png", "photo.png")
    return reverse("workspace:flex_file", args=[FlexFieldFile.parse_reference(reference)])


def test_ind_photo_is_served_within_the_selected_program(
    app: "DjangoTestApp", individual: "CountryIndividual", photo_url: str
) -> None:
    with select_office(app, individual.country_office, individual.program):
        res = app.get(photo_url)

    assert res.status_code == 200
    assert res.body == PHOTO
    assert res.content_type == "image/png"


def test_ind_photo_is_not_served_from_another_program(
    app: "DjangoTestApp", individual: "CountryIndividual", photo_url: str, other_program
) -> None:
    with select_office(app, other_program.country_office, other_program):
        res = app.get(photo_url, expect_errors=True)

    assert res.status_code == 404


def test_ind_photo_of_an_unknown_file_is_not_found(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:flex_file", args=[uuid4()])

    with select_office(app, individual.country_office, individual.program):
        res = app.get(url, expect_errors=True)

    assert res.status_code == 404


@pytest.fixture
def unmanaged_photo_url(individual: "CountryIndividual") -> str:
    """The url of a file whose owning model has no admin in the workspace."""
    from django.contrib.contenttypes.models import ContentType

    from country_workspace.models.flex_file import FlexFieldFile

    flex_file = FlexFieldFile.objects.create(
        content_type=ContentType.objects.get_for_model(FlexFieldFile),
        object_id=individual.pk,
        field_name="photo",
        content=PHOTO,
        mimetype="image/png",
        size=len(PHOTO),
    )
    return reverse("workspace:flex_file", args=[flex_file.pk])


def test_ind_photo_of_an_unmanaged_owner_is_denied(
    app: "DjangoTestApp", individual: "CountryIndividual", unmanaged_photo_url: str
) -> None:
    with select_office(app, individual.country_office, individual.program):
        res = app.get(unmanaged_photo_url, expect_errors=True)

    assert res.status_code == 403


@pytest.fixture
def photo_checker():
    """A checker with one image field next to a required text field."""
    from django import forms
    from testutils.factories import DataCheckerFactory

    from country_workspace.utils.flex_fields import FlexImageField

    return DataCheckerFactory(fields=[("photo", FlexImageField), ("family_name", forms.CharField)])


@pytest.fixture
def photo_program(office, photo_checker):
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(
        country_office=office,
        individual_checker=photo_checker,
        individual_columns="id\nfamily_name\nphoto",
        beneficiary_group__master_detail=False,
    )


@pytest.fixture
def individual_without_photo(photo_program):
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(batch__program=photo_program, household=None, flex_fields={"family_name": "Smith"})


def test_ind_change_form_attaches_an_uploaded_photo(
    app: "DjangoTestApp", individual_without_photo: "CountryIndividual"
) -> None:
    from io import BytesIO

    from PIL import Image
    from webtest import Upload

    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    png_bytes = buffer.getvalue()

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual_without_photo.country_office, individual_without_photo.program):
        res = app.get(url)
        res = res.click(individual_without_photo.name)
        form = res.forms["countryindividual_form"]
        form["flex_field-family_name"] = "Smith"
        form["flex_field-photo"] = Upload("photo.png", png_bytes, "image/png")
        res = form.submit()
        assert res.status_code == 302, res.location

    individual_without_photo.refresh_from_db()
    flex_file = individual_without_photo.flex_field_files.get()
    assert individual_without_photo.flex_fields["photo"] == flex_file.reference
    assert flex_file.content_bytes == png_bytes
    # attach_flex_files runs with update_raw_data=False on this path
    assert "photo" not in individual_without_photo.raw_data


def test_ind_changelist(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        assert res.status_code == 200, res.location
        assert f"Add {individual._meta.verbose_name}" not in res.text
        # filter by program
        res = app.get(url)
        assert res.status_code == 200, res.location
