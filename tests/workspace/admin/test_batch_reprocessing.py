from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from django.contrib.admin import AdminSite
from django.urls import reverse

from country_workspace.models import User
from country_workspace.models import AsyncJob, Batch
from country_workspace.workspaces.admin import CountryBatchAdmin
from country_workspace.workspaces.admin.batch import BatchReprocessForm
from country_workspace.workspaces.admin.batch_reprocessing import reprocess_batch
from country_workspace.workspaces.models import CountryBatch
from testutils.factories.program import BeneficiaryGroupFactory
from testutils.perms import user_grant_permissions

if TYPE_CHECKING:
    from django_webtest import DjangoTestApp
    from django_webtest.pytest_plugin import MixinWithInstanceVariables
    from pytest_django.fixtures import SettingsWrapper


pytestmark = [pytest.mark.django_db]


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def batch_admin_instance(admin_site) -> CountryBatchAdmin:
    return CountryBatchAdmin(CountryBatch, admin_site)


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    return OfficeFactory()


@pytest.fixture
def program(office, household_checker, individual_checker):
    from testutils.factories import CountryProgramFactory

    alien_individual_fields = [
        "phone_financial_institution",
        "national_passport_photo",
        "national_id_photo",
        "phone_number",
        "gender",
        "birth_date",
        "disability",
        "estimated_birth_date",
        "family_name",
        "full_name",
        "given_name",
        "household_id",
        "middle_name",
        "photo",
        "relationship",
        "national_id_document_number",
        "national_id_issuance_date",
        "national_id_expiry_date",
        "national_id_country",
        "national_passport_document_number",
        "national_passport_issuance_date",
        "national_passport_expiry_date",
        "national_passport_country",
        "bank_number",
        "bank_financial_institution",
    ]

    return CountryProgramFactory(
        country_office=office,
        household_checker=household_checker,
        individual_checker=individual_checker,
        household_columns="name\nid\nxx",
        individual_columns="name\nid\nxx",
        ind_alien_columns_to_ignore="\n".join(alien_individual_fields),
    )


@pytest.fixture
def batch_with_households(program):
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"size": 5},
    )
    return hh.batch


@pytest.fixture
def batch_with_individuals(program):
    from testutils.factories import CountryIndividualFactory

    ind = CountryIndividualFactory(
        household=None,
        batch__program=program,
        batch__country_office=program.country_office,
        flex_fields={"full_name": "John Doe"},
    )
    return ind.batch


@pytest.fixture
def app(django_app_factory: "MixinWithInstanceVariables") -> "DjangoTestApp":
    from testutils.factories import SuperUserFactory

    django_app = django_app_factory(csrf_checks=False)
    admin_user = SuperUserFactory(username="superuser")
    django_app.set_user(admin_user)
    django_app._user = admin_user
    return django_app


def test_reprocess_batch_with_households(
    batch_with_households: "CountryBatch", force_migrated_records, user: "User"
) -> None:
    """Test reprocessing batch with households."""
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(
        program=batch_with_households.program,
        batch=batch_with_households,
        owner=user,
        config={"batch_id": batch_with_households.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
        result = reprocess_batch(job)

        assert result["batch_id"] == batch_with_households.pk
        assert result["batch_name"] == batch_with_households.name
        households_count = result.get("households", 0)
        is_master_detail = batch_with_households.program.is_master_detail
        if is_master_detail:
            assert households_count > 0
        mock_create.assert_called_once()


def test_reprocess_batch_with_individuals(
    batch_with_individuals: "CountryBatch", force_migrated_records, user: "User"
) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(
        program=batch_with_individuals.program,
        batch=batch_with_individuals,
        owner=user,
        config={"batch_id": batch_with_individuals.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
        result = reprocess_batch(job)

        assert result["batch_id"] == batch_with_individuals.pk
        assert result["batch_name"] == batch_with_individuals.name
        assert result["individuals"] > 0
        mock_create.assert_called_once()


def test_reprocess_batch_missing_batch_id(user: "User") -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={})

    with pytest.raises(ValueError, match="batch_id is required"):
        reprocess_batch(job)


def test_reprocess_batch_nonexistent_batch(user: "User") -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(owner=user, config={"batch_id": 99999})

    with pytest.raises(Batch.DoesNotExist):
        reprocess_batch(job)


def test_reprocess_batch_empty_batch(program, user: "User") -> None:
    from testutils.factories import AsyncJobFactory, CountryBatchFactory

    empty_batch = CountryBatchFactory(program=program, country_office=program.country_office)
    job = AsyncJobFactory(
        program=program,
        batch=empty_batch,
        owner=user,
        config={"batch_id": empty_batch.pk},
    )

    result = reprocess_batch(job)

    assert result["batch_id"] == empty_batch.pk
    assert result.get("households", 0) == 0
    assert result["individuals"] == 0


def test_reprocess_batch_mixed_content(
    batch_with_households: "CountryBatch", force_migrated_records, user: "User"
) -> None:
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory

    # Add standalone individual to the batch
    CountryIndividualFactory(
        household=None,
        batch=batch_with_households,
        flex_fields={"full_name": "Jane Doe"},
    )

    job = AsyncJobFactory(
        program=batch_with_households.program,
        batch=batch_with_households,
        owner=user,
        config={"batch_id": batch_with_households.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
        result = reprocess_batch(job)

        is_master_detail = batch_with_households.program.is_master_detail
        if is_master_detail:
            assert result.get("households", 0) > 0
        assert result["individuals"] > 0
        mock_create.assert_called_once()


def test_reprocess_batch_permission_required(
    user: "User", batch_admin_instance: CountryBatchAdmin, batch_with_households: "CountryBatch", client
) -> None:
    url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

    client.force_login(user)
    client.post(reverse("workspace:select_tenant"), data={"tenant": batch_with_households.country_office.pk})

    response = client.get(url)
    assert response.status_code == 403

    with user_grant_permissions(user, "country_workspace.reprocess_batch", batch_with_households.program):
        client.post(
            reverse("workspace:select_tenant"),
            data={"tenant": batch_with_households.country_office.pk},
        )
        client.post(
            reverse("workspace:select_program"),
            data={"program": batch_with_households.program.pk},
        )
        response = client.get(url)
        assert response.status_code == 200


def test_reprocess_batch_permission_check_function(batch_with_households: "CountryBatch", user: "User") -> None:
    from country_workspace.workspaces.permissions import can_reprocess_batch

    request = Mock()
    request.user = user

    with patch.object(user, "has_perm", return_value=False):
        assert not can_reprocess_batch(request, batch_with_households)

    with patch.object(user, "has_perm", return_value=True):
        assert can_reprocess_batch(request, batch_with_households)


def test_reprocess_button_creates_job(
    app: "DjangoTestApp", batch_with_households: "CountryBatch", settings: "SettingsWrapper"
) -> None:
    from testutils.utils import select_office

    settings.CELERY_TASK_ALWAYS_EAGER = False
    url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

    with select_office(app, batch_with_households.country_office, batch_with_households.program):
        res = app.get(url)
        assert res.status_code == 200

        initial_job_count = AsyncJob.objects.count()
        form = res.forms[list(res.forms.keys())[-1]]
        res = form.submit()

        assert res.status_code == 302

        assert AsyncJob.objects.count() == initial_job_count + 1
        job = AsyncJob.objects.latest("id")
        assert job.batch == batch_with_households
        assert job.type == AsyncJob.JobType.TASK
        assert "batch_reprocessing.reprocess_batch" in job.action


def test_reprocess_button_confirmation_message(app: "DjangoTestApp", batch_with_households: "CountryBatch") -> None:
    from testutils.utils import select_office

    url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

    with select_office(app, batch_with_households.country_office, batch_with_households.program):
        res = app.get(url)
        assert res.status_code == 200
        assert batch_with_households.name in res.text
        assert "reprocess" in res.text.lower()
        assert "validate" in res.text.lower() or "re-validate" in res.text.lower()


def test_reprocess_button_with_nonexistent_batch(app: "DjangoTestApp", batch_with_households: "CountryBatch") -> None:
    from testutils.utils import select_office

    url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[99999])

    with select_office(app, batch_with_households.country_office, batch_with_households.program):
        res = app.get(url, expect_errors=True)
        assert res.status_code in [404, 500]


def test_reprocess_batch_form_hides_household_fields_for_people_program(household_checker, individual_checker) -> None:
    from testutils.factories import CountryProgramFactory

    beneficiary_group = BeneficiaryGroupFactory(master_detail=False)
    program = CountryProgramFactory(
        beneficiary_group=beneficiary_group,
        household_checker=household_checker,
        individual_checker=individual_checker,
    )

    form = BatchReprocessForm(program=program)

    assert "household_mapping" not in form.fields
    assert "household_transformer" not in form.fields
    assert "individual_mapping" in form.fields
    assert "individual_transformer" in form.fields


def test_reprocess_batch_form_pops_household_mapping_when_master_detail_and_no_household_checker(
    individual_checker,
) -> None:
    """When master_detail is True but household_checker is missing, household_mapping is removed."""
    from testutils.factories import CountryProgramFactory

    beneficiary_group = BeneficiaryGroupFactory(master_detail=True)
    program = CountryProgramFactory(
        beneficiary_group=beneficiary_group,
        household_checker=None,
        individual_checker=individual_checker,
    )

    form = BatchReprocessForm(program=program)

    assert "household_mapping" not in form.fields
    assert "household_transformer" in form.fields
    assert "individual_mapping" in form.fields
    assert "individual_transformer" in form.fields


def test_reprocess_batch_form_pops_individual_mapping_when_no_individual_checker(household_checker) -> None:
    """When individual_checker is missing, individual_mapping is removed."""
    from testutils.factories import CountryProgramFactory

    beneficiary_group = BeneficiaryGroupFactory(master_detail=True)
    program = CountryProgramFactory(
        beneficiary_group=beneficiary_group,
        household_checker=household_checker,
        individual_checker=None,
    )

    form = BatchReprocessForm(program=program)

    assert "household_mapping" in form.fields
    assert "household_transformer" in form.fields
    assert "individual_mapping" not in form.fields
    assert "individual_transformer" in form.fields


def test_full_reprocessing_workflow(
    app: "DjangoTestApp",
    batch_with_households: "CountryBatch",
    settings: "SettingsWrapper",
    force_migrated_records,
) -> None:
    from testutils.utils import select_office

    settings.CELERY_TASK_ALWAYS_EAGER = True
    url = reverse("workspace:workspaces_countrybatch_reprocess_batch", args=[batch_with_households.pk])

    with select_office(app, batch_with_households.country_office, batch_with_households.program):
        res = app.get(url)
        assert res.status_code == 200

        form = res.forms[list(res.forms.keys())[-1]]
        res = form.submit()
        assert res.status_code == 302

        job = AsyncJob.objects.filter(batch=batch_with_households).latest("id")
        assert job.batch == batch_with_households

        validation_jobs = AsyncJob.objects.filter(
            program=batch_with_households.program, description__icontains="Reprocess batch"
        )
        assert validation_jobs.exists()


def test_reprocess_batch_updates_validation_status(
    batch_with_households: "CountryBatch",
    force_migrated_records,
    user: "User",
    settings: "SettingsWrapper",
) -> None:
    from testutils.factories import AsyncJobFactory

    settings.CELERY_TASK_ALWAYS_EAGER = True

    household = batch_with_households.household_set.first()
    assert household is not None

    household.errors = {}
    household.last_checked = None
    household.save()

    job = AsyncJobFactory(
        program=batch_with_households.program,
        batch=batch_with_households,
        owner=user,
        config={"batch_id": batch_with_households.pk},
    )

    result = reprocess_batch(job)

    if (
        batch_with_households.program
        and batch_with_households.program.beneficiary_group
        and batch_with_households.program.beneficiary_group.master_detail
    ):
        assert result["households"] > 0


def test_reprocess_batch_excludes_removed_households(
    batch_with_households: "CountryBatch", force_migrated_records, user: "User"
) -> None:
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory

    CountryHouseholdFactory(
        batch=batch_with_households,
        flex_fields={"size": 3},
    )

    total_households = batch_with_households.household_set.count()
    assert total_households >= 2

    households = list(batch_with_households.household_set.all())
    for hh in households[::2]:
        hh.removed = True
        hh.save()

    removed_count = batch_with_households.household_set.filter(removed=True).count()
    not_removed_count = batch_with_households.household_set.filter(removed=False).count()

    job = AsyncJobFactory(
        program=batch_with_households.program,
        batch=batch_with_households,
        owner=user,
        config={"batch_id": batch_with_households.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
        result = reprocess_batch(job)

        if (
            batch_with_households.program
            and batch_with_households.program.beneficiary_group
            and batch_with_households.program.beneficiary_group.master_detail
        ):
            assert result["households"] == not_removed_count
            assert result["skipped_households"] == removed_count

        if mock_create.called:
            call_args = mock_create.call_args_list[0]
            queryset = call_args[1]["queryset"]
            assert queryset.filter(removed=True).count() == 0


def test_reprocess_batch_excludes_removed_individuals(
    batch_with_individuals: "CountryBatch", force_migrated_records, user: "User"
) -> None:
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory

    CountryIndividualFactory(
        household=None,
        batch=batch_with_individuals,
        flex_fields={"full_name": "Jane Doe"},
    )
    CountryIndividualFactory(
        household=None,
        batch=batch_with_individuals,
        flex_fields={"full_name": "Bob Smith"},
    )

    total_individuals = batch_with_individuals.individual_set.filter(household=None).count()
    assert total_individuals >= 3

    individuals = list(batch_with_individuals.individual_set.filter(household=None))
    for ind in individuals[:2]:
        ind.removed = True
        ind.save()

    removed_count = batch_with_individuals.individual_set.filter(household=None, removed=True).count()
    not_removed_count = batch_with_individuals.individual_set.filter(household=None, removed=False).count()

    job = AsyncJobFactory(
        program=batch_with_individuals.program,
        batch=batch_with_individuals,
        owner=user,
        config={"batch_id": batch_with_individuals.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
        result = reprocess_batch(job)

        assert result["individuals"] == not_removed_count
        assert result["skipped_individuals"] == removed_count

        if mock_create.called:
            call_args = mock_create.call_args_list[0]
            queryset = call_args[1]["queryset"]
            assert queryset.filter(removed=True).count() == 0


def test_reprocess_batch_all_removed(batch_with_households: "CountryBatch", user: "User") -> None:
    from testutils.factories import AsyncJobFactory

    batch_with_households.household_set.update(removed=True)
    batch_with_households.individual_set.update(removed=True)

    job = AsyncJobFactory(
        program=batch_with_households.program,
        batch=batch_with_households,
        owner=user,
        config={"batch_id": batch_with_households.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs") as mock_create:
        result = reprocess_batch(job)

        if (
            batch_with_households.program
            and batch_with_households.program.beneficiary_group
            and batch_with_households.program.beneficiary_group.master_detail
        ):
            assert result["households"] == 0
            assert result["skipped_households"] > 0
        assert result["individuals"] == 0
        assert result["skipped_individuals"] > 0

        mock_create.assert_not_called()


def test_reprocess_batch_mixed_removed_status(
    batch_with_households: "CountryBatch", force_migrated_records, user: "User"
) -> None:
    from testutils.factories import AsyncJobFactory, CountryIndividualFactory
    from testutils.factories.program import BeneficiaryGroupFactory

    bg = BeneficiaryGroupFactory(master_detail=True)
    batch_with_households.program.beneficiary_group = bg
    batch_with_households.program.save()

    CountryIndividualFactory(
        household=None,
        batch=batch_with_households,
        flex_fields={"full_name": "Standalone 1"},
    )
    CountryIndividualFactory(
        household=None,
        batch=batch_with_households,
        flex_fields={"full_name": "Standalone 2"},
    )

    household = batch_with_households.household_set.first()
    household.removed = True
    household.save()

    individual = batch_with_households.individual_set.filter(household=None).first()
    individual.removed = True
    individual.save()

    job = AsyncJobFactory(
        program=batch_with_households.program,
        batch=batch_with_households,
        owner=user,
        config={"batch_id": batch_with_households.pk},
    )

    with patch("country_workspace.workspaces.admin.batch_reprocessing.create_validation_jobs"):
        result = reprocess_batch(job)

        assert result.get("skipped_households", 0) == 1
        assert result.get("households", 0) >= 0
        assert result["individuals"] >= 1


def test_imported_records_with_beneficiary_group_master_detail_true(
    batch_admin_instance: CountryBatchAdmin, batch_with_households: "CountryBatch"
) -> None:
    bg = BeneficiaryGroupFactory(group_label="Custom Group", master_detail=True)
    batch_with_households.program.beneficiary_group = bg
    batch_with_households.program.save()

    btn = batch_admin_instance.imported_records.get_button({"original": batch_with_households})
    batch_admin_instance.imported_records.func(batch_admin_instance, btn)

    assert btn.label == "Custom Group"
    assert btn.visible is True
    assert "countryhousehold" in btn.href
    assert f"batch__exact={batch_with_households.pk}" in btn.href


def test_imported_records_with_beneficiary_group_master_detail_false(
    batch_admin_instance: CountryBatchAdmin, batch_with_households: "CountryBatch"
) -> None:
    bg = BeneficiaryGroupFactory(group_label="Custom Group", master_detail=False)
    batch_with_households.program.beneficiary_group = bg
    batch_with_households.program.save()

    btn = batch_admin_instance.imported_records.get_button({"original": batch_with_households})
    batch_admin_instance.imported_records.func(batch_admin_instance, btn)

    assert btn.label == "Custom Group"
    assert btn.visible is False
    assert "countryhousehold" in btn.href
    assert f"batch__exact={batch_with_households.pk}" in btn.href


def test_imported_records_without_beneficiary_group(
    batch_admin_instance: CountryBatchAdmin, batch_with_households: "CountryBatch"
) -> None:
    batch_with_households.program.beneficiary_group = None
    batch_with_households.program.save()

    btn = batch_admin_instance.imported_records.get_button({"original": batch_with_households})
    batch_admin_instance.imported_records.func(batch_admin_instance, btn)

    assert btn.visible is True
    assert "countryhousehold" in btn.href
    assert f"batch__exact={batch_with_households.pk}" in btn.href


def test_imported_records_with_beneficiary_group_uses_group_label(
    batch_admin_instance: CountryBatchAdmin, batch_with_households: "CountryBatch"
) -> None:
    bg = BeneficiaryGroupFactory(group_label="Custom Group", group_label_plural="Custom Groups", master_detail=True)
    batch_with_households.program.beneficiary_group = bg
    batch_with_households.program.save()

    btn = batch_admin_instance.imported_records.get_button({"original": batch_with_households})
    batch_admin_instance.imported_records.func(batch_admin_instance, btn)

    assert btn.label == "Custom Group"
    assert btn.visible is True


def test_imported_individuals_with_beneficiary_group(
    batch_admin_instance: CountryBatchAdmin, batch_with_individuals: "CountryBatch"
) -> None:
    bg = BeneficiaryGroupFactory(member_label="Custom Member")
    batch_with_individuals.program.beneficiary_group = bg
    batch_with_individuals.program.save()

    btn = batch_admin_instance.imported_individuals.get_button({"original": batch_with_individuals})
    batch_admin_instance.imported_individuals.func(batch_admin_instance, btn)

    assert btn.label == "Custom Member"
    assert btn.visible is True
    assert "countryindividual" in btn.href
    assert f"batch__exact={batch_with_individuals.pk}" in btn.href


def test_imported_individuals_without_beneficiary_group(
    batch_admin_instance: CountryBatchAdmin, batch_with_individuals: "CountryBatch"
) -> None:
    batch_with_individuals.program.beneficiary_group = None
    batch_with_individuals.program.save()

    btn = batch_admin_instance.imported_individuals.get_button({"original": batch_with_individuals})
    batch_admin_instance.imported_individuals.func(batch_admin_instance, btn)

    assert btn.visible is True
    assert "countryindividual" in btn.href
    assert f"batch__exact={batch_with_individuals.pk}" in btn.href


def test_imported_individuals_with_beneficiary_group_uses_member_label(
    batch_admin_instance: CountryBatchAdmin, batch_with_individuals: "CountryBatch"
) -> None:
    bg = BeneficiaryGroupFactory(member_label="Custom Member", member_label_plural="Custom Members")
    batch_with_individuals.program.beneficiary_group = bg
    batch_with_individuals.program.save()

    btn = batch_admin_instance.imported_individuals.get_button({"original": batch_with_individuals})
    batch_admin_instance.imported_individuals.func(batch_admin_instance, btn)

    assert btn.label == "Custom Member"
    assert btn.visible is True
