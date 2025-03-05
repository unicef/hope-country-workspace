from typing import Any, cast

from constance import config

from country_workspace.contrib.kobo.api.client.main import Client
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.models import AsyncJob, Batch, Individual, Household
from country_workspace.utils.fields import clean_field_name


def make_client(country_code: str | None) -> Client:
    token = config.KOBO_MASTER_API_TOKEN or config.KOBO_API_TOKEN
    project_view_id = config.KOBO_PROJECT_VIEW_ID if config.KOBO_MASTER_API_TOKEN else None
    return Client(
        base_url=config.KOBO_KF_URL,
        token=token,
        country_code=country_code,
        project_view_id=project_view_id,
    )


def extract_household_data(submission: Submission, individual_records_field: str) -> dict[str, Any]:
    return {key: value for key, value in submission.items() if key != individual_records_field}


def prepare_individuals(submission: Submission, individual_records_field: str, batch: Batch) -> list[Individual]:
    individuals = []
    for raw_individual in submission.get(individual_records_field, []):
        individual = {key.lstrip(f"{individual_records_field}/"): value for key, value in raw_individual.items()}
        fullname = next((key for key in individual if key.startswith("full_name")), None)
        individuals.append(
            Individual(
                batch=batch,
                name=individual.get(fullname, ""),
                flex_fields={clean_field_name(key): value for key, value in individual.items()},
            ),
        )
    return individuals


def create_household(batch: Batch, submission: Submission, individual_records_field: str) -> Household:
    household_fields = extract_household_data(submission, individual_records_field)
    return cast(
        Household,
        batch.program.households.create(
            batch=batch, flex_fields={clean_field_name(key): value for key, value in household_fields.items()}
        ),
    )


def import_data(job: AsyncJob) -> dict[str, int]:
    batch = Batch.objects.create(
        name=job.config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.KOBO,
    )
    individual_records_field = job.config["individual_records_field"]
    client = make_client(job.config["country_code"])
    household_counter = 0
    individual_counter = 0
    for asset in client.assets:
        for submission in asset.submissions:
            household = create_household(batch, submission, individual_records_field)
            household_counter += 1
            individuals = prepare_individuals(submission, individual_records_field, batch)
            household.program.individuals.bulk_create(individuals)
            individual_counter += len(individuals)

    return {"households": household_counter, "individuals": individual_counter}
