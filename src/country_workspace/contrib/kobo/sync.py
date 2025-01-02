from constance import config

from country_workspace.contrib.kobo.api.client import Client as KoboClient
from country_workspace.models import AsyncJob, KoboAsset, Batch, Individual
from country_workspace.utils.fields import clean_field_name


def sync_assets(_: AsyncJob) -> dict[str, int]:
    client = KoboClient(base_url=config.KOBO_BASE_URL, token=config.KOBO_TOKEN)
    created_assets = 0
    updated_assets = 0
    for asset in client.assets:
        asset_model, created = KoboAsset.objects.update_or_create(uid=asset.uid, defaults={"name": asset.name})
        if created:
            created_assets += 1
        else:
            updated_assets += 1

    return {"created": created_assets, "updated": updated_assets}


def sync_data(job: AsyncJob) -> dict[str, int]:
    batch = Batch.objects.create(
        name=job.config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.KOBO,
    )
    individual_records_field = job.config["individual_records_field"]
    client = KoboClient(base_url=config.KOBO_BASE_URL, token=config.KOBO_TOKEN)
    assets = (asset for asset in client.assets if asset.uid in job.config["assets"])
    for asset in assets:
        for submission in asset.submissions:
            household_fields = {key: value for key, value in submission if key != individual_records_field}
            household = batch.program.households.create(batch=batch, flex_fields={clean_field_name(key): value for key, value in household_fields.items()})
            individuals = []
            for individual in submission[individual_records_field]:
                fullname = next((key for key in individual if key.startswith("given_name")), None)
                individuals.append(
                    Individual(
                        batch=batch,
                        household_id=household.pk,
                        name=individual.get(fullname, ""),
                        flex_fields={clean_field_name(key): value for key, value in individual.items()},
                    ),
                )
    return {"households": 0, "individuals": 0}
