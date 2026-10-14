from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from pytest_mock import MockerFixture
from django.core.exceptions import ValidationError
from django.urls import reverse
from testutils.utils import select_office

from country_workspace.models import Rdp, RdpOperation
from country_workspace.state import state
from country_workspace.workspaces.admin import individual as individual_admin_mod
from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin
from country_workspace.workspaces.admin.individual import CountryIndividualAdmin

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables

    from country_workspace.workspaces.models import CountryIndividual

pytestmark = [pytest.mark.admin, pytest.mark.smoke, pytest.mark.django_db]


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


@pytest.mark.parametrize("removed", [False, True], ids=["active", "removed"])
def test_common_context_duplicate_url(
    individual_admin: CountryIndividualAdmin,
    individual: "CountryIndividual",
    rf,
    mocker: MockerFixture,
    removed: bool,
) -> None:
    from testutils.factories import CountryIndividualFactory

    duplicate = CountryIndividualFactory(household=None, batch=individual.batch, removed=removed)
    individual._result_available = True

    mocker.patch.object(
        BeneficiaryBaseAdmin,
        "get_common_context",
        return_value={"original": individual},
    )
    mocker.patch.object(individual_admin, "get_selected_household", return_value=individual.household)

    rdp = mocker.sentinel.rdp
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    findings = mocker.patch.object(
        individual_admin_mod,
        "biometric_findings_for_individual",
        return_value=({duplicate.pk: 101}, ["BAD_IMAGE_QUALITY"]),
    )

    base_url = f"/individuals/{duplicate.pk}/"
    mocker.patch.object(individual_admin_mod, "reverse", return_value=base_url)

    context = individual_admin.get_common_context(rf.get("/"))

    expected_url = base_url
    if removed:
        preserved = urlencode({"_changelist_filters": urlencode({"rdp_id": 101})})
        expected_url = f"{base_url}?{preserved}"

    assert context["dedup_duplicates"] == [{"pk": duplicate.pk, "url": expected_url}]
    assert context["dedup_image_issues"] == ["BAD_IMAGE_QUALITY"]
    findings.assert_called_once_with(individual=individual, rdp=rdp)


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


def test_get_object_without_object_id(
    individual_admin: CountryIndividualAdmin,
    rf,
    mocker: MockerFixture,
) -> None:
    base = mocker.patch.object(BeneficiaryBaseAdmin, "get_object")

    assert individual_admin.get_object(rf.get("/"), None) is None

    base.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [None, RdpOperation.Status.PENDING],
    ids=["missing-operation", "operation-not-successful"],
)
def test_get_object_requires_successful_biometric_operation(
    individual_admin: CountryIndividualAdmin,
    rf,
    mocker: MockerFixture,
    status: RdpOperation.Status | None,
) -> None:
    rdp = mocker.sentinel.rdp
    operation = RdpOperation(status=status) if status is not None else None

    mocker.patch.object(BeneficiaryBaseAdmin, "get_object", return_value=None)
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    get_operation = mocker.patch.object(
        individual_admin_mod,
        "biometric_operation_for_rdp",
        return_value=operation,
    )
    duplicates = mocker.patch.object(individual_admin_mod, "qs_biometric_duplicate_individuals")

    assert individual_admin.get_object(rf.get("/"), "1") is None

    get_operation.assert_called_once_with(rdp=rdp)
    duplicates.assert_not_called()


@pytest.mark.parametrize(
    "error_type",
    [ValidationError, ValueError],
    ids=["validation-error", "value-error"],
)
def test_get_object_invalid_object_id(
    individual_admin: CountryIndividualAdmin,
    rf,
    mocker: MockerFixture,
    error_type: type[Exception],
) -> None:
    rdp = mocker.sentinel.rdp
    operation = RdpOperation(status=RdpOperation.Status.SUCCESS)

    mocker.patch.object(BeneficiaryBaseAdmin, "get_object", return_value=None)
    mocker.patch.object(individual_admin_mod, "get_rdp_context", return_value=rdp)
    mocker.patch.object(individual_admin_mod, "biometric_operation_for_rdp", return_value=operation)
    mocker.patch.object(individual_admin.model._meta.pk, "to_python", side_effect=error_type("invalid"))
    duplicates = mocker.patch.object(individual_admin_mod, "qs_biometric_duplicate_individuals")

    assert individual_admin.get_object(rf.get("/"), "invalid") is None

    duplicates.assert_not_called()


def test_ind_change_missing_object_redirects(app: "DjangoTestApp", individual: "CountryIndividual") -> None:
    url = reverse("workspace:workspaces_countryindividual_change", args=[2**63 - 1])

    with select_office(app, individual.country_office, individual.program):
        response = app.get(url, status=302)

    assert response.status_code == 302


@pytest.mark.parametrize(
    "rdp_status",
    [Rdp.PushStatus.SUCCESS, Rdp.PushStatus.REVIEW_PENDING],
    ids=["historical", "review-pending"],
)
def test_ind_change_opens_removed_biometric_duplicate_from_rdp(
    app: "DjangoTestApp",
    program,
    rdp_status: Rdp.PushStatus,
) -> None:
    from testutils.factories import (
        BiometricRdpOperationFactory,
        BiometricRdpOperationFindingFactory,
        CountryIndividualFactory,
    )

    from country_workspace.contrib.dedup_engine import FindingStatusCode
    from country_workspace.models import Batch, RdpOperation

    program.beneficiary_group.master_detail = False
    program.beneficiary_group.save(update_fields=["master_detail"])

    current = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        batch__status=Batch.BatchStatus.COMPLETE,
        removed=rdp_status == Rdp.PushStatus.SUCCESS,
    )
    duplicate = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        batch__status=Batch.BatchStatus.COMPLETE,
        removed=True,
    )
    unrelated = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        batch__status=Batch.BatchStatus.COMPLETE,
        removed=True,
    )

    rdp = Rdp.objects.create(
        country_office=program.country_office,
        program=program,
        pushed_by=app._user,
        status=rdp_status,
    )
    rdp.individuals.add(current)

    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=current,
        related_individual=duplicate,
    )

    with select_office(app, program.country_office, program):
        current_url = reverse("workspace:workspaces_countryindividual_change", args=[current.pk])
        response = app.get(current_url, params={"rdp_id": rdp.pk})

        duplicate_url = response.context["dedup_duplicates"][0]["url"]
        duplicate_response = app.get(duplicate_url)

        assert duplicate_response.status_code == 200
        assert duplicate_response.context["original"].pk == duplicate.pk
        assert duplicate_response.context["has_change_permission"] is False

        unrelated_url = reverse("workspace:workspaces_countryindividual_change", args=[unrelated.pk])
        app.get(
            unrelated_url,
            params={"_changelist_filters": urlencode({"rdp_id": rdp.pk})},
            status=302,
        )
