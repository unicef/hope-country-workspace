from constance import config

from country_workspace.contrib.kobo.api.client.main import Client
from country_workspace.models import AsyncJob, Batch, Individual
from country_workspace.utils.fields import clean_field_name


def import_data(job: AsyncJob) -> dict[str, int]:
    batch = Batch.objects.create(
        name=job.config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.KOBO,
    )
    individual_records_field = job.config["individual_records_field"]
    token = config.KOBO_MASTER_API_TOKEN or config.KOBO_API_TOKEN
    project_view_id = config.KOBO_PROJECT_VIEW_ID if config.KOBO_MASTER_API_TOKEN else None
    client = Client(
        base_url=config.KOBO_KF_URL,
        token=token,
        country_code=job.config["country_code"],
        project_view_id=project_view_id,
    )
    household_counter = 0
    individual_counter = 0
    for asset in client.assets:
        for submission in asset.submissions:
            household_fields = {key: value for key, value in submission.items() if key != individual_records_field}
            household = batch.program.households.create(
                batch=batch, flex_fields={clean_field_name(key): value for key, value in household_fields.items()}
            )
            household_counter += 1
            individuals = []
            for raw_individual in submission.get(individual_records_field, []):
                individual = {
                    key.lstrip(f"{individual_records_field}/"): value for key, value in raw_individual.items()
                }
                fullname = next((key for key in individual if key.startswith("full_name")), None)
                individuals.append(
                    Individual(
                        batch=batch,
                        name=individual.get(fullname, ""),
                        flex_fields={clean_field_name(key): value for key, value in individual.items()},
                    ),
                )
            household.program.individuals.bulk_create(individuals)
            household_counter += len(individuals)
    return {"households": household_counter, "individuals": individual_counter}
