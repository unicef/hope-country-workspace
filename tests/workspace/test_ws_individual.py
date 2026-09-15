from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.state import state
from country_workspace.workspaces.admin import individual as individual_admin_mod
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin
from country_workspace.workspaces.admin.individual import CountryIndividualAdmin

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
def individual_admin(mocker: MockerFixture) -> CountryIndividualAdmin:
    from country_workspace.workspaces.models import CountryIndividual

    return CountryIndividualAdmin(CountryIndividual, mocker.MagicMock())


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


def test_ind_change_form_shows_latin_name_under_name(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {**individual.flex_fields, "full_name_latin": "Zvezdana Petrovic"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)

        assert res.status_code == 200, res.location
        assert "Zvezdana Petrovic" in res.text


def test_ind_change_form_hides_latin_name_when_absent(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {k: v for k, v in individual.flex_fields.items() if k != "full_name_latin"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        res = res.click(individual.name)

        assert res.status_code == 200, res.location
        assert "text-muted" not in res.text


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


def test_ind_changelist(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)
        assert res.status_code == 200, res.location
        assert f"Add {individual._meta.verbose_name}" not in res.text
        # filter by program
        res = app.get(url)
        assert res.status_code == 200, res.location


def test_ind_changelist_shows_latin_name_under_name(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {**individual.flex_fields, "full_name_latin": "Zvezdana Petrovic"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)

        assert res.status_code == 200, res.location
        assert individual.name in res.text
        assert "Zvezdana Petrovic" in res.text


def test_ind_changelist_hides_latin_name_when_absent(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    individual.flex_fields = {k: v for k, v in individual.flex_fields.items() if k != "full_name_latin"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url)

        assert res.status_code == 200, res.location
        assert individual.name in res.text


def test_ind_changelist_search_by_latin_name(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    # Charset-agnostic search: matching on the Latin spelling must find the individual, even
    # when the term does not appear in the (local-script) `name`.
    individual.flex_fields = {**individual.flex_fields, "full_name_latin": "Zvezdana Petrovic"}
    individual.save(update_fields=["flex_fields"])

    url = reverse("workspace:workspaces_countryindividual_changelist")
    with select_office(app, individual.country_office, individual.program):
        res = app.get(url, params={"q": "Zvezdana"})

        assert res.status_code == 200, res.location
        assert individual.name in res.text


@pytest.mark.parametrize(
    ("available", "value", "expected"),
    [
        (False, True, None),
        (True, True, True),
        (True, False, False),
    ],
)
def test_is_duplicate(
    individual_admin: CountryIndividualAdmin,
    individual: "CountryIndividual",
    available: bool,
    value: bool,
    expected: bool | None,
) -> None:
    individual._result_available = available
    individual._is_duplicate = value

    assert individual_admin.is_duplicate(individual) is expected


@pytest.mark.parametrize(
    ("available", "value", "expected"),
    [
        (False, True, None),
        (True, True, True),
        (True, False, False),
    ],
)
def test_has_image_issue(
    individual_admin: CountryIndividualAdmin,
    individual: "CountryIndividual",
    available: bool,
    value: bool,
    expected: bool | None,
) -> None:
    individual._result_available = available
    individual._has_image_issue = value

    assert individual_admin.has_image_issue(individual) is expected


def test_common_context_without_biometric_result(
    individual_admin: CountryIndividualAdmin,
    individual: "CountryIndividual",
    rf,
    mocker: MockerFixture,
) -> None:
    individual._result_available = False
    mocker.patch.object(
        BeneficiaryBaseAdmin,
        "get_common_context",
        return_value={"original": individual},
    )
    findings = mocker.patch.object(individual_admin_mod, "biometric_findings_for_individual")

    context = individual_admin.get_common_context(rf.get("/"))

    assert context["dedup_duplicates"] is None
    assert context["dedup_image_issues"] is None
    findings.assert_not_called()


def test_common_context_with_biometric_result(
    individual_admin: CountryIndividualAdmin,
    individual: "CountryIndividual",
    rf,
    mocker: MockerFixture,
) -> None:
    individual._result_available = True
    mocker.patch.object(
        BeneficiaryBaseAdmin,
        "get_common_context",
        return_value={"original": individual},
    )
    mocker.patch.object(individual_admin, "get_selected_household", return_value=individual.household)
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=None)
    findings = mocker.patch.object(
        individual_admin_mod,
        "biometric_findings_for_individual",
        return_value=([11, 22], ["BAD_IMAGE_QUALITY"]),
    )
    reverse = mocker.patch.object(
        individual_admin_mod,
        "reverse",
        side_effect=lambda _name, args: f"/individuals/{args[0]}/",
    )

    context = individual_admin.get_common_context(rf.get("/"))

    assert context["dedup_duplicates"] == [
        {"pk": 11, "url": "/individuals/11/"},
        {"pk": 22, "url": "/individuals/22/"},
    ]
    assert context["dedup_image_issues"] == ["BAD_IMAGE_QUALITY"]
    findings.assert_called_once_with(individual=individual, rdp=None)
    assert reverse.call_count == 2


@pytest.mark.parametrize(
    ("visible", "expected"),
    [
        (True, {"is_duplicate", "has_image_issue"}),
        (False, set()),
    ],
)
def test_biometric_columns_visibility(
    individual_admin: CountryIndividualAdmin,
    rf,
    mocker: MockerFixture,
    visible: bool,
    expected: set[str],
) -> None:
    mocker.patch.object(BeneficiaryBaseAdmin, "get_list_display", return_value=["name"])
    mocker.patch.object(individual_admin_mod, "show_biometric_columns", return_value=visible)

    columns = set(individual_admin.get_list_display(rf.get("/")))

    assert expected <= columns
    if not visible:
        assert not {"is_duplicate", "has_image_issue"} & columns


@pytest.mark.parametrize(
    ("visible", "expected"),
    [
        (True, {"DuplicateFilter", "ImageIssueFilter"}),
        (False, set()),
    ],
)
def test_biometric_filters_visibility(
    individual_admin: CountryIndividualAdmin,
    rf,
    mocker: MockerFixture,
    visible: bool,
    expected: set[str],
) -> None:
    mocker.patch.object(BeneficiaryBaseAdmin, "get_list_filter", return_value=[])
    mocker.patch.object(individual_admin_mod, "show_biometric_columns", return_value=visible)

    filters = individual_admin.get_list_filter(rf.get("/"))
    names = {filter_.__name__ for filter_ in filters if isinstance(filter_, type)}

    assert expected <= names
    if not visible:
        assert not {"DuplicateFilter", "ImageIssueFilter"} & names


@pytest.mark.parametrize("visible", [True, False], ids=["biometric", "plain"])
def test_queryset_biometric_annotations(
    individual_admin: CountryIndividualAdmin,
    program,
    rf,
    mocker: MockerFixture,
    visible: bool,
) -> None:
    state.program = program
    queryset = mocker.MagicMock()
    base = mocker.patch.object(BeneficiaryBaseAdmin, "get_queryset", return_value=queryset)
    mocker.patch.object(individual_admin_mod, "show_biometric_columns", return_value=visible)
    rdp = mocker.Mock()
    get_rdp = mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    annotate = mocker.patch.object(
        individual_admin_mod,
        "annotate_biometric_individuals",
        return_value=mocker.sentinel.annotated,
    )

    result = individual_admin.get_queryset(rf.get("/"))
    filtered = queryset.select_related.return_value.filter.return_value

    base.assert_called_once()
    if visible:
        assert result is mocker.sentinel.annotated
        annotate.assert_called_once_with(filtered, program=program, rdp=rdp)
        get_rdp.assert_called_once()
    else:
        assert result is filtered
        annotate.assert_not_called()
        get_rdp.assert_not_called()
