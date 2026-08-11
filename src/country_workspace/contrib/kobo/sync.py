import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, NotRequired, TypedDict, cast, TYPE_CHECKING
from urllib.parse import urlparse
from constance import config as constance_config
from django.utils import timezone
from django.db import transaction
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from django.contrib.contenttypes.models import ContentType

from country_workspace.contrib.kobo.exceptions import AlienFieldsError

from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.utils.auth import Auth
from country_workspace.contrib.kobo.api.client.main import Client
from country_workspace.contrib.kobo.api.common import DataGetter
from country_workspace.contrib.kobo.api.data.asset import Asset
from country_workspace.contrib.kobo.api.data.submission import Submission
from country_workspace.models import AsyncJob, Batch, Household, Individual, Program, SyncLog
from country_workspace.models.household import (
    RELATIONSHIP_HEAD,
    RELATIONSHIP_NON_BENEFICIARY,
    ROLE_ALTERNATE,
    ROLE_PRIMARY,
)
from country_workspace.utils.config import BatchNameConfig, ValidateModeConfig
from country_workspace.utils.fields import TO_UPPERCASE_FIELDS
from country_workspace.utils.imports import get_kobo_originating_id
from country_workspace.utils.import_flow import (
    build_import_processor,
    get_or_create_collector,
    run_batch_postprocessing,
)
from country_workspace.utils.sync_log import get_kobo_sync_log_name
from country_workspace.workspaces.admin.cleaners.validate import create_validation_jobs
from country_workspace.models.jobs import GracefulJobCancellationError
from country_workspace.notifications.signals import data_imported_signal

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class Config(BatchNameConfig, ValidateModeConfig):
    project_id: str
    individual_records_field: str
    household_mapping_id: NotRequired[int | None]
    individual_mapping_id: NotRequired[int | None]
    household_transformer_id: NotRequired[int | None]
    individual_transformer_id: NotRequired[int | None]


ACCEPT_JSON_HEADERS: Final[dict[str, str]] = {"Accept": "application/json"}

RETRY_TOTAL: Final[int] = 5
RETRY_BACKOFF_FACTOR: Final[float] = 1.0
RETRY_STATUS_FORCELIST: Final[tuple[int, ...]] = (429, 502, 503, 504)
RETRY_ALLOWED_METHODS: Final[frozenset[str]] = frozenset(("GET", "HEAD", "OPTIONS"))

SUBMISSION_PATH_RE = re.compile(r".*/assets/[^/]+/data(?:/.*)?$")

INDIVIDUAL_FIELDS_TO_UPPERCASE = ("role",)
HOUSEHOLD_FIELDS_TO_UPPERCASE = ("registration_method", "residence_status", "consent_sharing")


def is_submission_data_url(url: str) -> bool:
    return bool(SUBMISSION_PATH_RE.match(urlparse(url).path))


def make_client(country_code: str) -> Client:
    session = Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(("GET",)),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
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


KOBO_SYS_FIELD_PREFIX = "kobo_sys__"


def filter_kobo_sys_fields(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not key.split("/")[-1].startswith(KOBO_SYS_FIELD_PREFIX)}


def normalize_json(data: dict[str, Any]) -> dict[str, Any]:
    return {key.split("/")[-1]: value for key, value in data.items()}


type Raw = dict[str, Any]


def build_household_processor(
    program: Program,
    mapping_id: int | None,
    *,
    apply_defaults: bool = True,
    apply_mapping: bool = True,
    post_processors: Iterable[Callable[[Raw], Raw]] | None = None,
) -> Callable[[Raw], Raw]:
    return cast(
        "Callable[[Raw], Raw]",
        build_import_processor(
            program=program,
            model=Household,
            mapping_id=mapping_id,
            fields_to_uppercase=HOUSEHOLD_FIELDS_TO_UPPERCASE,
            pre_processors=(filter_kobo_sys_fields, normalize_json),
            post_processors=post_processors,
            apply_defaults=apply_defaults,
            apply_mapping=apply_mapping,
            source=Batch.BatchSource.KOBO,
        ),
    )


def build_individual_processor(
    program: Program,
    mapping_id: int | None,
    *,
    apply_defaults: bool = True,
    apply_mapping: bool = True,
    post_processors: Iterable[Callable[[Raw], Raw]] | None = None,
) -> Callable[[Raw], Raw]:
    return cast(
        "Callable[[Raw], Raw]",
        build_import_processor(
            program=program,
            model=Individual,
            mapping_id=mapping_id,
            fields_to_uppercase=INDIVIDUAL_FIELDS_TO_UPPERCASE + TO_UPPERCASE_FIELDS,
            pre_processors=(filter_kobo_sys_fields, normalize_json),
            post_processors=post_processors,
            apply_defaults=apply_defaults,
            apply_mapping=apply_mapping,
            source=Batch.BatchSource.KOBO,
        ),
    )


def get_fullname_key(individual: Iterable[str]) -> str | None:
    return next((key for key in individual if key.startswith("full_name")), None)


@dataclass(frozen=True)
class ImportedIndividual:
    """An individual record paired with its occurrence-specific processed fields."""

    individual: Individual
    fields: dict[str, Any]
    created: bool = True


def create_individuals(  # noqa: PLR0913
    batch: Batch,
    household: Household,
    submission: Submission,
    config: Config,
    originating_id: str,
    job: AsyncJob | None = None,
) -> list[ImportedIndividual]:
    individuals: list[ImportedIndividual] = []
    individual_mapping_id = config.get("individual_mapping_id")
    for idx, raw_individual in enumerate(submission.get(config["individual_records_field"], []), start=1):
        if job:
            job.ensure_not_cancelled(refresh=True)
        individual_fields = build_individual_processor(
            batch.program,
            individual_mapping_id,
        )(raw_individual)
        fullname = get_fullname_key(cast("Iterable[str]", individual_fields.keys()))
        name = individual_fields.get(fullname, "") if fullname else ""
        ind_originating_id = f"{originating_id}#{idx:04d}"
        if individual_fields.get("relationship") == RELATIONSHIP_NON_BENEFICIARY:
            # External collectors are deduplicated program-wide: the first
            # occurrence is reused, linked to households only via role refs.
            individual, created = get_or_create_collector(
                program=batch.program,
                batch=batch,
                individual_fields=individual_fields,
                raw_data=raw_individual,
                originating_id=ind_originating_id,
                name=name,
            )
            individuals.append(ImportedIndividual(individual=individual, fields=individual_fields, created=created))
        else:
            individual = Individual(
                batch=batch,
                household=household,
                name=name,
                originating_id=ind_originating_id,
                flex_fields=individual_fields,
                raw_data=raw_individual,
            )
            individuals.append(ImportedIndividual(individual=individual, fields=individual_fields))
    household.program.individuals.bulk_create([item.individual for item in individuals if item.individual.pk is None])
    return individuals


def create_household(
    batch: Batch,
    submission: Submission,
    config: Config,
    id_generator: Callable[[], int],
    originating_id: str,
) -> Household:
    household_mapping_id = config.get("household_mapping_id")
    raw_household_fields = extract_household_data(submission, config["individual_records_field"])
    household_fields = build_household_processor(
        batch.program,
        household_mapping_id,
    )(raw_household_fields)
    household_fields["household_id"] = id_generator()
    return cast(
        "Household",
        batch.program.households.create(
            batch=batch,
            originating_id=originating_id,
            flex_fields=household_fields,
            raw_data=raw_household_fields,
        ),
    )


class ImportResult(TypedDict):
    households: int
    individuals: int
    completed: bool


def _is_primary_collector(imported: ImportedIndividual) -> bool:
    return imported.fields.get("role") == ROLE_PRIMARY


def _is_alternate_collector(imported: ImportedIndividual) -> bool:
    return imported.fields.get("role") == ROLE_ALTERNATE


def _is_head_of_household(imported: ImportedIndividual) -> bool:
    return imported.fields.get("relationship") == RELATIONSHIP_HEAD


def set_roles_and_relationships(household: Household, individuals: list[ImportedIndividual]) -> None:
    fields = HOUSEHOLD_ROLE_REF_FIELDS
    if primary_collector := next((item.individual for item in individuals if _is_primary_collector(item)), None):
        household.flex_fields[fields.primary_collector] = primary_collector.id
    if alternate_collector := next((item.individual for item in individuals if _is_alternate_collector(item)), None):
        household.flex_fields[fields.alternate_collector] = alternate_collector.id
    if head_of_household := next((item.individual for item in individuals if _is_head_of_household(item)), None):
        household.flex_fields[fields.head_of_household] = head_of_household.id
    household.save(update_fields=["flex_fields"])


def get_allowed_fields(checker: "DataChecker | None") -> set[str]:
    """Get set of allowed field names from a DataChecker."""
    if not checker:
        return set()
    return {f"{fieldset.prefix}{field.name}" for fieldset, field in list(checker.get_fields())}  # type: ignore[misc]


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
    raw_household_fields = extract_household_data(submission, config["individual_records_field"])
    household_fields = build_household_processor(
        batch.program,
        mapping_id=None,
        apply_defaults=False,
        apply_mapping=False,
        post_processors=(mapping_importer,),
    )(raw_household_fields)

    household_allowed_fields = get_allowed_fields(batch.program.household_checker)
    household_alien = get_alien_fields(
        data=household_fields,
        allowed_fields=household_allowed_fields,
        extras={config["individual_records_field"]},
    )

    individual_alien: set[str] = set()
    if individuals_data := submission.get(config["individual_records_field"]):
        first_individual = individuals_data[0]
        individual_fields = build_individual_processor(
            batch.program,
            mapping_id=None,
            apply_defaults=False,
            apply_mapping=False,
            post_processors=(mapping_importer,),
        )(first_individual)
        individual_allowed_fields = get_allowed_fields(batch.program.individual_checker)
        individual_alien = get_alien_fields(
            data=individual_fields,
            allowed_fields=individual_allowed_fields,
            extras={config["individual_records_field"]},
        )

    if household_alien or individual_alien:
        raise AlienFieldsError(household_alien, individual_alien)


def import_asset(  # noqa: PLR0913
    batch: Batch,
    asset: Asset,
    config: Config,
    id_generator: Callable[[], int],
    *,
    job: AsyncJob | None = None,
    timebox_seconds: int | None = None,
) -> ImportResult:
    household_counter = 0
    individual_counter = 0
    sync_log_name = get_kobo_sync_log_name(asset.uid)

    program_ct = ContentType.objects.get_for_model(Program)
    sync_log = SyncLog.objects.filter(name=sync_log_name, content_type=program_ct, object_id=batch.program.id).first()
    last_id = int(sync_log.last_id) if sync_log and sync_log.last_id else 0

    last_successful_id = last_id
    current_submission = None

    start_time = timezone.now()
    time_exhausted = False

    submissions_iterator = asset.submissions(min_id=last_id)

    try:
        for submission in submissions_iterator:
            if job:
                job.ensure_not_cancelled(refresh=True)
            current_submission = submission
            originating_id = get_kobo_originating_id(asset.uid, str(submission.id))
            # One transaction per submission: if this block fails, only this
            # submission is rolled back; previously committed data stays.
            with transaction.atomic():
                household = create_household(batch, submission, config, id_generator, originating_id)
                individuals = create_individuals(batch, household, submission, config, originating_id, job=job)
                set_roles_and_relationships(household, individuals)

                household_counter += 1
                individual_counter += sum(1 for item in individuals if item.created)

            last_successful_id = submission.id
            if timebox_seconds is not None:
                elapsed_seconds = (timezone.now() - start_time).total_seconds()
                if elapsed_seconds >= timebox_seconds:
                    time_exhausted = True
                    break

    except GracefulJobCancellationError:
        raise
    except Exception as e:
        failed_id = current_submission.id if current_submission else "unknown (before first submission)"

        error_msg = (
            f"Successfully imported {household_counter} households, before stopping at submission {failed_id} due to:"
            f"Error: {e}"
            f"Last successful submission ID: {last_successful_id}."
        )
        raise ImportError(error_msg) from e

    finally:
        # Persist watermark so the next run (or retry) resumes after the last
        # successful submission; runs even when an exception is raised.
        if last_successful_id > last_id:
            SyncLog.objects.update_or_create(
                name=sync_log_name,
                content_type=program_ct,
                object_id=batch.program.id,
                defaults={"last_id": str(last_successful_id), "last_update_date": timezone.now()},
            )

    return ImportResult(
        households=household_counter,
        individuals=individual_counter,
        completed=not time_exhausted,
    )


def get_id_generator(start: int = 0) -> Callable[[], int]:
    last_id = start

    def id_generator() -> int:
        nonlocal last_id

        last_id += 1
        return last_id

    return id_generator


def import_data(job: AsyncJob) -> ImportResult:
    """
    Import Kobo asset data for a job.

    Transaction management:
    - Batch setup (create or lock batch, set status to LOADING) runs in a single
      atomic block so the batch is visible and locked before import starts.
    - import_asset() runs outside that block; it commits each submission in its
      own transaction (see import_asset). That way, partial progress is persisted
      and the watermark (SyncLog) can be updated per submission.
    - On success, batch status is updated to COMPLETE in a final atomic block.
    - On incomplete (timebox or reschedule), a new AsyncJob is queued; no batch
      status change until the run that completes.
    """
    from country_workspace.workspaces.admin._import_data import KOBO_IMPORT_JOB_DESCRIPTION

    config: Config = job.config
    job.ensure_not_cancelled(refresh=True)

    # Create or lock the batch and set status to LOADING in one transaction.
    with transaction.atomic():
        batch_id = getattr(job, "batch_id", None)
        if batch_id:
            batch = (
                Batch.objects.select_for_update().select_related("program", "program__country_office").get(pk=batch_id)
            )
        else:
            batch = Batch.objects.create(
                name=config["batch_name"],
                program=job.program,
                country_office=job.program.country_office,
                imported_by=job.owner,
                source=Batch.BatchSource.KOBO,
                status=Batch.BatchStatus.LOADING,
            )
            job.batch = batch
            job.save(update_fields=["batch"])

        if batch.status != Batch.BatchStatus.LOADING:
            batch.status = Batch.BatchStatus.LOADING
            batch.save(update_fields=["status"])

    id_generator = get_id_generator(start=batch.household_set.count())
    client = make_client(job.program.country_office.kobo_country_code)

    household_counter = 0
    individual_counter = 0

    asset = client.get_asset(config["project_id"])
    timebox_minutes = getattr(constance_config, "KOBO_IMPORT_TIMEBOX_MINUTES", 0) or 0
    timebox_seconds = int(timebox_minutes * 60) if timebox_minutes > 0 else None

    # import_asset commits each submission in its own transaction; on error it
    # raises after updating the watermark so the next run can resume.
    asset_import_result = import_asset(
        batch,
        asset,
        config,
        id_generator,
        job=job,
        timebox_seconds=timebox_seconds,
    )
    household_counter += asset_import_result["households"]
    individual_counter += asset_import_result["individuals"]

    if asset_import_result["completed"]:
        run_batch_postprocessing(
            batch,
            household_transformer_id=config.get("household_transformer_id"),
            individual_transformer_id=config.get("individual_transformer_id"),
        )
        if config.get("validate_after_import"):
            job.ensure_not_cancelled(refresh=True)
            create_validation_jobs(
                description=f"Validate records for batch {batch.pk}",
                owner=job.owner,
                program=job.program,
                queryset=batch.household_set.filter(removed=False).prefetch_related("members"),  # type: ignore[attr-defined]
                validation_scope="batch",
            )
        job.ensure_not_cancelled(refresh=True)
        # Mark batch complete in a dedicated transaction.
        with transaction.atomic():
            Batch.objects.select_for_update().filter(pk=batch.pk).update(status=Batch.BatchStatus.COMPLETE)

        data_imported_signal.send(
            sender=Batch,
            program_id=batch.program_id,
            batch_id=batch.id,
            record_count=batch.household_set.count() + batch.individual_set.count(),
            source=Batch.BatchSource.KOBO,
        )
    else:
        job.ensure_not_cancelled(refresh=True)
        AsyncJob.objects.create(
            description=KOBO_IMPORT_JOB_DESCRIPTION.format(program_name=job.program.name),
            type=job.type,
            action=job.action,
            file=getattr(job, "file", None),
            program=job.program,
            owner=job.owner,
            config=config,
            batch=batch,
        ).queue()

    return ImportResult(
        households=household_counter,
        individuals=individual_counter,
        completed=asset_import_result["completed"],
    )
