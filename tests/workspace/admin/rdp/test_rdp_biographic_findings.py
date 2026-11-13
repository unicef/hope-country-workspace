import pytest
from django.urls import reverse
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.biographic.types import BiographicFindingType
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp

pytestmark = pytest.mark.django_db


@pytest.fixture
def biographic_operation(rdp: CountryRdp) -> RdpOperation:
    from testutils.factories import BiographicRdpOperationFactory

    return BiographicRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)


def test_operations_display_successful_biographic(
    admin_instance,
    biographic_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    from testutils.factories import BiographicRdpOperationFindingFactory

    BiographicRdpOperationFindingFactory(operation=biographic_operation)
    affected = mocker.patch.object(rdp_admin_mod, "qs_biographic_affected_individuals")
    affected.return_value.count.return_value = 2
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    assert admin_instance.operations_display(biographic_operation.rdp) == "rendered"

    row = render.call_args.args[1]["rows"][0]
    assert row["operation_id"] == str(biographic_operation.id)
    assert row["findings"] == 1
    assert row["affected_individuals"] == 2
    affected.assert_called_once_with(operation=biographic_operation)


def test_operations_display_failed_biographic_skips_affected_individuals(
    admin_instance,
    biographic_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    RdpOperation.objects.filter(pk=biographic_operation.pk).update(status=RdpOperation.Status.FAILURE)
    affected = mocker.patch.object(rdp_admin_mod, "qs_biographic_affected_individuals")
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    admin_instance.operations_display(biographic_operation.rdp)

    assert render.call_args.args[1]["rows"][0]["affected_individuals"] is None
    affected.assert_not_called()


def test_findings_page_shows_biographic_details(client, rdp: CountryRdp, biographic_operation: RdpOperation) -> None:
    from testutils.factories import BiographicRdpOperationFindingFactory, CountryIndividualFactory, UserFactory

    first = CountryIndividualFactory(household=None, batch__program=rdp.program, name="Jane Doe")
    second = CountryIndividualFactory(household=None, batch__program=rdp.program, name="Jane Dough")
    BiographicRdpOperationFindingFactory(
        operation=biographic_operation,
        individual=first,
        related_individual=second,
        details={
            "scope": "population",
            "related_reference_pk": second.pk,
            "score": 0.97,
            "proximity_to_score": 0.12,
            "matched_full_name": "Jane Dough",
            "matched_birth_date": "1990-05-06",
        },
    )
    BiographicRdpOperationFindingFactory(
        operation=biographic_operation,
        individual=second,
        related_individual=None,
        details={"scope": "batch", "related_reference_pk": 999_999, "score": 0.9},
    )
    user = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": rdp.country_office.pk})
    client.post(reverse("workspace:select_program"), data={"program": rdp.program.pk})

    response = client.get(
        reverse("workspace:workspaces_countryrdp_findings", args=[rdp.pk, biographic_operation.pk]),
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert str(BiographicFindingType.DUPLICATE.label) in html
    assert "Approved population" in html
    assert "This RDP" in html
    assert "0.97" in html
    assert "Proximity to score" in html
    assert "0.12" in html
    assert "Jane Dough" in html
    assert "(1990-05-06)" in html
    assert "#999999" in html
