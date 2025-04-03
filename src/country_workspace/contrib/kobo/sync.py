import re
from typing import Any, TypedDict, cast, Final

from constance import config as constance_config
from django.core.cache import cache
from requests import Session

from country_workspace.contrib.kobo.api.client.auth import Auth
from country_workspace.contrib.kobo.api.client.main import Client
from country_workspace.contrib.kobo.api.common import DataGetter
from country_workspace.contrib.kobo.api.data.asset import Asset
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.contrib.kobo.models import KoboSubmission
from country_workspace.models import AsyncJob, Batch, Household, Individual
from country_workspace.utils.config import FailIfAlienConfig, BatchNameConfig
from country_workspace.utils.fields import clean_field_names


class Config(BatchNameConfig, FailIfAlienConfig):
    project_id: str
    individual_records_field: str


ACCEPT_JSON_HEADERS: Final[dict[str, str]] = {"Accept": "application/json"}

SUBMISSION_URL_RE = re.compile(".+/assets/[^/]+/data/.*")


def is_submission_data_url(url: str) -> bool:
    return bool(SUBMISSION_URL_RE.match(url))


def make_client(country_code: str | None) -> Client:
    session = Session()
    token = constance_config.KOBO_MASTER_API_TOKEN or constance_config.KOBO_API_TOKEN
    session.auth = Auth(token)
    data_getter = DataGetter(
        session=session,
        cache_ttl=constance_config.KOBO_CACHE_TTL,
        headers=ACCEPT_JSON_HEADERS,
        do_not_use_cache_if=is_submission_data_url,
    )
    project_view_id = constance_config.KOBO_PROJECT_VIEW_ID if constance_config.KOBO_MASTER_API_TOKEN else None

    return Client(
        data_getter=data_getter,
        base_url=constance_config.KOBO_KF_URL,
        country_code=country_code,
        project_view_id=project_view_id,
    )


def extract_household_data(submission: Submission, individual_records_field: str) -> dict[str, Any]:
    return {key: value for key, value in submission.items() if key != individual_records_field}


def create_individuals(batch: Batch, household: Household, submission: Submission, config: Config) -> int:
    individuals = []
    for raw_individual in submission.get(config["individual_records_field"], []):
        individual = {
            key.replace(f"{config['individual_records_field']}/", ""): value for key, value in raw_individual.items()
        }
        fullname = next((key for key in individual if key.startswith("full_name")), None)
        individuals.append(
            Individual(
                batch=batch,
                household=household,
                name=individual.get(fullname, ""),
                flex_fields=clean_field_names(individual),
            ),
        )
    household.program.individuals.bulk_create(individuals)
    return len(individuals)


def create_household(batch: Batch, submission: Submission, config: Config) -> Household:
    household_fields = extract_household_data(submission, config["individual_records_field"])
    return cast(
        Household,
        batch.program.households.create(
            batch=batch,
            flex_fields=clean_field_names(household_fields),
        ),
    )


ASSET_CACHE_KEY = "sync_kobo_asset_{asset_id}"


class ImportResult(TypedDict):
    households: int
    individuals: int


def import_asset(batch: Batch, asset: Asset, config: Config) -> ImportResult:
    household_counter = 0
    individual_counter = 0

    with cache.lock(ASSET_CACHE_KEY.format(asset_id=asset.uid)):
        submission_ids = set(KoboSubmission.objects.filter(asset_uid=asset.uid).values_list("submission_id", flat=True))
        for submission in asset.submissions:
            if submission.id in submission_ids:
                continue
            household = create_household(batch, submission, config)
            household_counter += 1
            individual_counter += create_individuals(batch, household, submission, config)

    return ImportResult(households=household_counter, individuals=individual_counter)


def import_data(job: AsyncJob) -> ImportResult:
    config: Config = job.config

    batch = Batch.objects.create(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.KOBO,
    )
    client = make_client(job.program.country_office.kobo_country_code)

    household_counter = 0
    individual_counter = 0

    for asset in client.assets:
        # TODO: fetch specific asset
        if config["project_id"] == asset.uid:
            import_result = import_asset(batch, asset, config)
            household_counter += import_result["households"]
            individual_counter += import_result["individuals"]

    return ImportResult(households=household_counter, individuals=individual_counter)
