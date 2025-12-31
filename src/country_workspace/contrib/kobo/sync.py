import re
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, Final, NotRequired, TypedDict, cast, TYPE_CHECKING
from constance import config as constance_config
from django.utils import timezone
from requests import Session
from requests.adapters import HTTPAdapter

from django.contrib.contenttypes.models import ContentType

from country_workspace.contrib.kobo.exceptions import AlienFieldsError


from country_workspace.contrib.kobo.api.client.auth import Auth
from country_workspace.contrib.kobo.api.client.main import Client
from country_workspace.contrib.kobo.api.common import DataGetter
from country_workspace.contrib.kobo.api.data.asset import Asset
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.models import AsyncJob, Batch, Household, Individual, Program, SyncLog
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.fields import clean_field_names, TO_UPPERCASE_FIELDS
from country_workspace.utils.functional import compose
from country_workspace.utils.sync_log import get_kobo_sync_log_name
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class Config(BatchNameConfig, ValidateModeConfig):
    project_id: str
    individual_records_field: str
    household_mapping_id: NotRequired[int | None]
    individual_mapping_id: NotRequired[int | None]


ACCEPT_JSON_HEADERS: Final[dict[str, str]] = {"Accept": "application/json"}

SUBMISSION_URL_RE = re.compile(".+/assets/[^/]+/data/.*")

INDIVIDUAL_FIELDS_TO_UPPERCASE = ("role",)
HOUSEHOLD_FIELDS_TO_UPPERCASE = ("registration_method", "residence_status", "consent_sharing")


def is_submission_data_url(url: str) -> bool:
    return bool(SUBMISSION_URL_RE.match(url))


def make_client(country_code: str) -> Client:
    session = Session()
    session.mount("https://", HTTPAdapter(max_retries=3))
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


def normalize_json(data: dict[str, Any]) -> dict[str, Any]:
    return {key.split("/")[-1]: value for key, value in data.items()}


type Raw = dict[str, Any]


def preprocess(
    raw: Raw,
    fields_to_uppercase: tuple[str, ...],
    mapping_importer: Callable[[Raw], Raw],
    default_fields_applier: Callable[[Raw], Raw],
) -> Raw:
    clean: Callable[[Raw], Raw] = partial(clean_field_names, fields_to_uppercase=fields_to_uppercase)
    processor: Callable[[Raw], Raw] = compose(normalize_json, clean, mapping_importer, default_fields_applier)
    return processor(raw)


def get_fullname_key(individual: Iterable[str]) -> str | None:
    return next((key for key in individual if key.startswith("full_name")), None)


def create_individuals(batch: Batch, household: Household, submission: Submission, config: Config) -> list[Individual]:
    individuals = []
    individual_mapping_id = config.get("individual_mapping_id")
    for raw_individual in submission.get(config["individual_records_field"], []):
        individual_fields = preprocess(
            raw_individual,
            INDIVIDUAL_FIELDS_TO_UPPERCASE + TO_UPPERCASE_FIELDS,
            partial(batch.program.apply_mapping_importer, Individual, mapping_id=individual_mapping_id),
            partial(batch.program.apply_default_fields, Individual),
        )
        fullname = get_fullname_key(individual_fields)
        individuals.append(
            Individual(
                batch=batch,
                household=household,
                name=individual_fields.get(fullname, "") if fullname else "",
                flex_fields=individual_fields,
                raw_data=individual_fields,
            ),
        )
    household.program.individuals.bulk_create(individuals)
    return individuals


def create_household(
    batch: Batch, submission: Submission, config: Config, id_generator: Callable[[], int]
) -> Household:
    household_mapping_id = config.get("household_mapping_id")
    raw_household_fields = extract_household_data(submission, config["individual_records_field"])
    household_fields = preprocess(
        raw_household_fields,
        HOUSEHOLD_FIELDS_TO_UPPERCASE,
        partial(batch.program.apply_mapping_importer, Household, mapping_id=household_mapping_id),
        partial(batch.program.apply_default_fields, Household),
    )
    household_fields["household_id"] = id_generator()
    return cast(
        "Household",
        batch.program.households.create(
            batch=batch,
            flex_fields=household_fields,
            raw_data=household_fields,
        ),
    )


class ImportResult(TypedDict):
    households: int
    individuals: int


def _is_primary_collector(individual: Individual) -> bool:
    return individual.flex_fields.get("role") == "PRIMARY"


def _is_alternate_collector(individual: Individual) -> bool:
    return individual.flex_fields.get("role") == "ALTERNATE"


def _is_head_of_household(individual: Individual) -> bool:
    return individual.flex_fields.get("relationship") == "HEAD"


def set_roles_and_relationships(household: Household, individuals: list[Individual]) -> None:
    if primary_collector := next(filter(_is_primary_collector, individuals), None):
        household.flex_fields["primary_collector"] = primary_collector.id

    if alternate_collector := next(filter(_is_alternate_collector, individuals), None):
        household.flex_fields["alternate_collector"] = alternate_collector.id

    if head_of_household := next(filter(_is_head_of_household, individuals), None):
        household.flex_fields["head_of_household"] = head_of_household.id

    household.save(update_fields=["flex_fields"])


def get_allowed_fields(checker: "DataChecker | None") -> set[str]:
    """Get set of allowed field names from a DataChecker."""
    if not checker:
        return set()
    return {f"{fieldset.prefix}{field.name}" for fieldset, field in list(checker.get_fields())}


def get_alien_fields(data: dict[str, Any], allowed_fields: set[str], extras: set | None = None) -> set[str]:
    """Return fields in data that are not in allowed_fields."""
    data_fields = set(data.keys())
    kobo_specific_fields = {
        field.strip() for field in constance_config.KOBO_FIELDS_TO_IGNORE.split(",") if field.strip()
    }
    extras = extras or set()
    return data_fields - kobo_specific_fields - set(extras) - allowed_fields


def check_for_alien_fields(
    batch: Batch, submission: Submission, config: Config, mapping_importer: Callable[[Raw], Raw]
) -> None:
    """Check first submission for alien fields and raise if found."""
    default_fields_applier = lambda x: x
    raw_household_fields = extract_household_data(submission, config["individual_records_field"])
    household_fields = preprocess(
        raw_household_fields,
        HOUSEHOLD_FIELDS_TO_UPPERCASE,
        partial(mapping_importer, Household),
        default_fields_applier,
    )

    household_allowed_fields = get_allowed_fields(batch.program.household_checker)
    household_alien = get_alien_fields(
        data=household_fields,
        allowed_fields=household_allowed_fields,
        extras={config["individual_records_field"]},
    )

    individual_alien: set[str] = set()
    if individuals_data := submission.get(config["individual_records_field"]):
        first_individual = individuals_data[0]
        individual_fields = preprocess(
            first_individual,
            INDIVIDUAL_FIELDS_TO_UPPERCASE + TO_UPPERCASE_FIELDS,
            partial(mapping_importer, Individual),
            default_fields_applier,
        )
        individual_allowed_fields = get_allowed_fields(batch.program.individual_checker)
        individual_alien = get_alien_fields(
            data=individual_fields,
            allowed_fields=individual_allowed_fields,
            extras={config["individual_records_field"]},
        )

    if household_alien or individual_alien:
        raise AlienFieldsError(household_alien, individual_alien)


def import_asset(batch: Batch, asset: Asset, config: Config, id_generator: Callable[[], int]) -> ImportResult:
    from django.db import transaction

    household_counter = 0
    individual_counter = 0
    sync_log_name = get_kobo_sync_log_name(asset.uid)

    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLog.objects.filter(name=sync_log_name, content_type=program_ct, object_id=batch.program.id).first()
    last_id = int(sync_log.last_id) if sync_log and sync_log.last_id else 0

    last_successful_id = last_id
    current_submission = None

    submissions_iterator = asset.submissions(min_id=last_id)

    try:
        for submission in submissions_iterator:
            current_submission = submission

            with transaction.atomic():
                household = create_household(batch, submission, config, id_generator)
                individuals = create_individuals(batch, household, submission, config)
                set_roles_and_relationships(household, individuals)

                household_counter += 1
                individual_counter += len(individuals)

            last_successful_id = submission.id

    except Exception as e:
        failed_id = current_submission.id if current_submission else "unknown (before first submission)"

        error_msg = (
            f"Successfully imported {household_counter} households, before stopping at submission {failed_id} due to:"
            f"Error: {e}"
            f"Last successful submission ID: {last_successful_id}."
        )
        raise ImportError(error_msg) from e

    finally:
        if last_successful_id > last_id:
            SyncLog.objects.update_or_create(
                name=sync_log_name,
                content_type=program_ct,
                object_id=batch.program.id,
                defaults={"last_id": str(last_successful_id), "last_update_date": timezone.now()},
            )

    return ImportResult(households=household_counter, individuals=individual_counter)


def get_id_generator() -> Callable[[], int]:
    last_id = 0

    def id_generator() -> int:
        nonlocal last_id

        last_id += 1
        return last_id

    return id_generator


def import_data(job: AsyncJob) -> ImportResult:
    config: Config = job.config

    batch = Batch.objects.create(
        name=config["batch_name"],
        program=job.program,
        country_office=job.program.country_office,
        imported_by=job.owner,
        source=Batch.BatchSource.KOBO,
    )
    id_generator = get_id_generator()
    client = make_client(job.program.country_office.kobo_country_code)

    household_counter = 0
    individual_counter = 0

    asset = client.get_asset(config["project_id"])
    import_result = import_asset(batch, asset, config, id_generator)
    household_counter += import_result["households"]
    individual_counter += import_result["individuals"]

    if config.get("validate_after_import"):
        create_validation_jobs(
            description=f"Validate records for batch {batch.pk}",
            owner=job.owner,
            program=job.program,
            queryset=batch.household_set.all().prefetch_related("members"),
        )

    return ImportResult(households=household_counter, individuals=individual_counter)
