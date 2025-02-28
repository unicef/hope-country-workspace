from constance import config

from country_workspace.contrib.kobo.api.client import Client
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
    client = Client(
        base_url=config.KOBO_BASE_URL, token=config.KOBO_TOKEN, country_code=job.program.country_office.code
    )
    for asset in client.assets:
        for submission in asset.submissions:
            household_fields = {key: value for key, value in submission if key != individual_records_field}
            household = batch.program.households.create(
                batch=batch, flex_fields={clean_field_name(key): value for key, value in household_fields.items()}
            )
            individuals = []
            for individual in submission[individual_records_field]:
                fullname = next((key for key in individual if key.startswith("given_name")), None)
                individuals.append(
                    Individual(
                        batch=batch,
                        name=individual.get(fullname, ""),
                        flex_fields={clean_field_name(key): value for key, value in individual.items()},
                    ),
                )
            household.individual_set.bulk_create(individuals)
    return {"households": 0, "individuals": 0}
