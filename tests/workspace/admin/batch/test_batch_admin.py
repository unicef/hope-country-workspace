import pytest
from strategy_field.utils import fqn
from django.test import RequestFactory

from country_workspace.models import AsyncJob
from country_workspace.workspaces.admin.batch import BatchReprocessForm
from country_workspace.workspaces.admin.batch.reprocessing import reprocess_batch as reprocess_batch_task
from country_workspace.workspaces.models import CountryBatch


pytestmark = pytest.mark.django_db


def test_reprocess_form_hides_household_fields_for_people_program(people_program) -> None:
    form = BatchReprocessForm(program=people_program)

    assert "household_mapping" not in form.fields
    assert "household_transformer" not in form.fields
    assert "individual_mapping" in form.fields
    assert "individual_transformer" in form.fields


def test_reprocess_form_hides_missing_checker_mapping_fields(program) -> None:
    program.household_checker = None
    program.individual_checker = None
    program.save(update_fields=["household_checker", "individual_checker"])

    form = BatchReprocessForm(program=program)

    assert "household_mapping" not in form.fields
    assert "individual_mapping" not in form.fields
    assert "household_transformer" in form.fields
    assert "individual_transformer" in form.fields


def test_reprocess_form_filters_mappings_and_transformers_by_program(program) -> None:
    from testutils.factories import MappingImporterFactory, OfficeFactory, TransformerFactory

    other_office = OfficeFactory()
    household_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.household_checker,
        rules="a=b",
    )
    individual_mapping = MappingImporterFactory(
        office=program.country_office,
        data_checker=program.individual_checker,
        rules="c=d",
    )
    transformer = TransformerFactory(office=program.country_office)
    other_transformer = TransformerFactory(office=other_office)

    form = BatchReprocessForm(program=program)

    assert form.fields["household_mapping"].queryset.filter(pk=household_mapping.pk).exists()
    assert form.fields["individual_mapping"].queryset.filter(pk=individual_mapping.pk).exists()
    assert form.fields["household_transformer"].queryset.filter(pk=transformer.pk).exists()
    assert not form.fields["household_transformer"].queryset.filter(pk=other_transformer.pk).exists()


def test_reprocess_button_creates_task_job(
    batch_admin,
    batch: CountryBatch,
    user,
    rf: RequestFactory,
    mocker,
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module

    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(batch_admin, "get_common_context")
    mocker.patch.object(AsyncJob, "queue")
    mocker.patch.object(batch_admin_module, "reverse", return_value="/batches/")

    request = rf.post("/", data={"apply": "1"})
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302

    job = AsyncJob.objects.latest("pk")
    assert job.batch == batch
    assert job.description.startswith("Reprocess batch: ")
    assert job.type == AsyncJob.JobType.TASK
    assert job.owner == user
    assert job.program == batch.program
    assert job.config == {"batch_id": batch.pk}
    assert job.action == fqn(reprocess_batch_task)


def test_reprocess_button_includes_selected_mapping_and_transformer_ids(
    batch_admin,
    batch: CountryBatch,
    user,
    rf: RequestFactory,
    mocker,
) -> None:
    from country_workspace.workspaces.admin.batch import admin as batch_admin_module
    from testutils.factories import MappingImporterFactory, TransformerFactory

    household_mapping = MappingImporterFactory(
        office=batch.country_office,
        data_checker=batch.program.household_checker,
        rules="hh_external=hh_internal",
    )
    individual_mapping = MappingImporterFactory(
        office=batch.country_office,
        data_checker=batch.program.individual_checker,
        rules="ind_external=ind_internal",
    )
    household_transformer = TransformerFactory(office=batch.country_office)
    individual_transformer = TransformerFactory(office=batch.country_office)

    mocker.patch.object(batch_admin, "get_object", return_value=batch)
    mocker.patch.object(batch_admin, "message_user")
    mocker.patch.object(AsyncJob, "queue")
    mocker.patch.object(batch_admin_module, "reverse", return_value="/batches/")

    request = rf.post(
        "/",
        data={
            "apply": "1",
            "household_mapping": str(household_mapping.pk),
            "individual_mapping": str(individual_mapping.pk),
            "household_transformer": str(household_transformer.pk),
            "individual_transformer": str(individual_transformer.pk),
        },
    )
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, str(batch.pk))

    assert response.status_code == 302

    job = AsyncJob.objects.latest("pk")
    assert job.config == {
        "batch_id": batch.pk,
        "household_mapping_id": household_mapping.pk,
        "individual_mapping_id": individual_mapping.pk,
        "household_transformer_id": household_transformer.pk,
        "individual_transformer_id": individual_transformer.pk,
    }


def test_reprocess_button_returns_404_for_missing_batch(batch_admin, rf: RequestFactory, user, mocker) -> None:
    mocker.patch.object(batch_admin, "get_object", return_value=None)

    request = rf.get("/")
    request.user = user

    response = batch_admin.reprocess_batch.func(batch_admin, request, "999999")

    assert response.status_code == 404
    assert response.content == b"Batch not found"


@pytest.mark.parametrize(
    ("master_detail", "expected_visible"),
    [
        (True, True),
        (False, False),
    ],
)
def test_imported_records_button_visibility(
    batch_admin, batch: CountryBatch, master_detail: bool, expected_visible: bool
) -> None:
    from testutils.factories.program import BeneficiaryGroupFactory

    batch.program.beneficiary_group = BeneficiaryGroupFactory(group_label="Group", master_detail=master_detail)
    batch.program.save(update_fields=["beneficiary_group"])

    button = batch_admin.imported_records.get_button({"original": batch})
    batch_admin.imported_records.func(batch_admin, button)

    assert button.label == "Group"
    assert button.visible is expected_visible
    assert f"batch__exact={batch.pk}" in button.href


def test_imported_individuals_button_uses_member_label(batch_admin, batch: CountryBatch) -> None:
    from testutils.factories.program import BeneficiaryGroupFactory

    batch.program.beneficiary_group = BeneficiaryGroupFactory(member_label="Member")
    batch.program.save(update_fields=["beneficiary_group"])

    button = batch_admin.imported_individuals.get_button({"original": batch})
    batch_admin.imported_individuals.func(batch_admin, button)

    assert button.label == "Member"
    assert button.visible is True
    assert f"batch__exact={batch.pk}" in button.href
