import pytest
from django.contrib.admin import AdminSite
from django.test import Client
from django.urls import reverse
from django.utils.translation import gettext as _
from strategy_field.utils import fqn

from country_workspace.admin.batch import BatchAdmin
from country_workspace.models import AsyncJob, Batch
from country_workspace.tasks import batch_cleanup as batch_cleanup_task


pytestmark = [pytest.mark.django_db]


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def batch_admin_instance(admin_site) -> BatchAdmin:
    admin = BatchAdmin(Batch, admin_site)
    admin.households.model_admin = admin
    admin.individuals.model_admin = admin
    return admin


@pytest.fixture
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture
def empty_batch(program):
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


@pytest.fixture
def batch_with_households(program):
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
    )
    return hh.batch


class TestBatchAdminHouseholdsButton:
    """Test BatchAdmin.households link button."""

    def test_households_button_no_households(self, batch_admin_instance: BatchAdmin, empty_batch: "Batch") -> None:
        """Test households button is hidden when batch has no households."""
        btn = batch_admin_instance.households.get_button({"original": empty_batch})
        batch_admin_instance.households.func(batch_admin_instance, btn)

        assert btn.visible is False

    def test_households_button_master_detail_false(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test households button is hidden when master_detail is False."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(master_detail=False)
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        btn = batch_admin_instance.households.get_button({"original": batch_with_households})
        batch_admin_instance.households.func(batch_admin_instance, btn)

        assert btn.visible is False

    def test_households_button_master_detail_true_with_custom_label(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test households button is visible with custom label when master_detail is True."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(
            group_label="Custom Group",
            group_label_plural="Custom Groups",
            master_detail=True,
        )
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        btn = batch_admin_instance.households.get_button({"original": batch_with_households})
        batch_admin_instance.households.func(batch_admin_instance, btn)

        assert btn.visible is True
        assert btn.label == "Custom Groups"  # Uses plural
        assert "/admin/country_workspace/household/" in btn.href
        assert f"batch__exact={batch_with_households.pk}" in btn.href

    def test_households_button_master_detail_true_with_singular_label(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test households button uses singular label when plural is empty."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(
            group_label="Custom Group",
            group_label_plural="",  # Empty string to test fallback
            master_detail=True,
        )
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        btn = batch_admin_instance.households.get_button({"original": batch_with_households})
        batch_admin_instance.households.func(batch_admin_instance, btn)

        assert btn.visible is True
        assert btn.label == "Custom Group"  # Uses singular when plural is empty
        assert "/admin/country_workspace/household/" in btn.href

    def test_households_button_master_detail_true_no_labels(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test households button uses default label when labels are empty."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(
            group_label="",
            group_label_plural="",
            master_detail=True,
        )
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        btn = batch_admin_instance.households.get_button({"original": batch_with_households})
        batch_admin_instance.households.func(batch_admin_instance, btn)

        assert btn.visible is True
        assert btn.label == _("Household")  # Default fallback
        assert "/admin/country_workspace/household/" in btn.href

    def test_households_button_no_beneficiary_group(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test households button is visible with default label when no beneficiary_group."""
        batch_with_households.program.beneficiary_group = None
        batch_with_households.program.save()

        btn = batch_admin_instance.households.get_button({"original": batch_with_households})
        batch_admin_instance.households.func(batch_admin_instance, btn)

        assert btn.visible is True
        assert "/admin/country_workspace/household/" in btn.href
        assert f"batch__exact={batch_with_households.pk}" in btn.href


class TestBatchAdminImportPicturesButton:
    """Test BatchAdmin.import_pictures link button."""

    def test_import_pictures_button_visible_with_permission(
        self, batch_admin_instance: BatchAdmin, empty_batch: "Batch", mocker
    ) -> None:
        request = mocker.MagicMock()
        request.user.has_perm.return_value = True

        btn = batch_admin_instance.import_pictures.get_button({"original": empty_batch, "request": request})
        batch_admin_instance.import_pictures.func(batch_admin_instance, btn)

        assert btn.visible is True
        assert btn.href.endswith(f"/workspace/workspaces/countrybatch/{empty_batch.pk}/import_pictures/")

    def test_import_pictures_button_hidden_without_permission(
        self, batch_admin_instance: BatchAdmin, empty_batch: "Batch", mocker
    ) -> None:
        request = mocker.MagicMock()
        request.user.has_perm.return_value = False

        btn = batch_admin_instance.import_pictures.get_button({"original": empty_batch, "request": request})
        batch_admin_instance.import_pictures.func(batch_admin_instance, btn)

        assert btn.visible is False


class TestBatchAdminGetBeneficiaryLabels:
    """Test BatchAdmin._get_beneficiary_labels method."""

    def test_get_beneficiary_labels_with_custom_labels(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test _get_beneficiary_labels with custom labels."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(
            group_label="Custom Group",
            group_label_plural="Custom Groups",
            member_label="Custom Member",
            member_label_plural="Custom Members",
        )
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        group_label, member_label = batch_admin_instance._get_beneficiary_labels(batch_with_households)

        assert group_label == "Custom Groups"
        assert member_label == "Custom Members"

    def test_get_beneficiary_labels_with_singular_labels_only(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test _get_beneficiary_labels falls back to singular when plural is empty."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(
            group_label="Custom Group",
            group_label_plural="",  # Empty string to test fallback
            member_label="Custom Member",
            member_label_plural="",  # Empty string to test fallback
        )
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        group_label, member_label = batch_admin_instance._get_beneficiary_labels(batch_with_households)

        assert group_label == "Custom Group"
        assert member_label == "Custom Member"

    def test_get_beneficiary_labels_with_no_labels(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test _get_beneficiary_labels uses defaults when labels are empty."""
        from testutils.factories.program import BeneficiaryGroupFactory

        bg = BeneficiaryGroupFactory(
            group_label="",
            group_label_plural="",
            member_label="",
            member_label_plural="",
        )
        batch_with_households.program.beneficiary_group = bg
        batch_with_households.program.save()

        group_label, member_label = batch_admin_instance._get_beneficiary_labels(batch_with_households)

        assert group_label == _("Household")
        assert member_label == _("Individual")

    def test_get_beneficiary_labels_no_beneficiary_group(
        self, batch_admin_instance: BatchAdmin, batch_with_households: "Batch"
    ) -> None:
        """Test _get_beneficiary_labels returns defaults when no beneficiary_group."""
        batch_with_households.program.beneficiary_group = None
        batch_with_households.program.save()

        group_label, member_label = batch_admin_instance._get_beneficiary_labels(batch_with_households)

        assert group_label == _("Household")
        assert member_label == _("Individual")


class TestBatchAdminBeneficiariesButton:
    """Test BatchAdmin.beneficiaries view (All Beneficiaries button)."""

    def test_beneficiaries_when_batch_loading_returns_empty_querysets(self, empty_batch: "Batch") -> None:
        """When batch status is LOADING, households and individuals are empty querysets."""
        from testutils.factories import SuperUserFactory

        empty_batch.status = Batch.BatchStatus.LOADING
        empty_batch.save()

        user = SuperUserFactory(username="beneficiaries_test_user")
        client = Client()
        client.force_login(user)

        url = reverse("admin:country_workspace_batch_beneficiaries", args=[empty_batch.pk])
        response = client.get(url)

        assert response.status_code == 200


@pytest.fixture
def admin_client():
    from testutils.factories import SuperUserFactory

    user = SuperUserFactory(username="batch_cleanup_admin")
    client = Client()
    client.force_login(user)
    return client


def test_batch_cleanup_button_shows_confirmation(admin_client, empty_batch):
    url = reverse("admin:country_workspace_batch_batch_cleanup", args=[empty_batch.pk])
    response = admin_client.get(url)

    assert response.status_code == 200
    assert AsyncJob.objects.filter(batch=empty_batch).count() == 0


def test_batch_cleanup_button_schedules_job_on_confirm(admin_client, empty_batch, mocker):
    spy = mocker.patch.object(AsyncJob, "queue", autospec=True, return_value=None)

    url = reverse("admin:country_workspace_batch_batch_cleanup", args=[empty_batch.pk])
    response = admin_client.post(url)

    assert response.status_code == 302
    job = AsyncJob.objects.filter(batch=empty_batch).first()
    assert job is not None
    assert job.type == AsyncJob.JobType.TASK
    assert job.action == fqn(batch_cleanup_task)
    assert job.program == empty_batch.program
    assert spy.call_count == 1


def test_batch_admin_disables_default_delete(batch_admin_instance):
    assert batch_admin_instance.has_delete_permission(request=None) is False
    assert batch_admin_instance.has_delete_permission(request=None, obj=None) is False
