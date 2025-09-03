import logging
from collections.abc import Generator, Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from io import TextIOBase
from typing import Any, Final, TypedDict, NotRequired, TextIO, Literal

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Model

from country_workspace.exceptions import RemoteError
from ..client import HopeClient
from ....models import SyncLog

logging.basicConfig()


MESSAGES: Final[dict[str, str]] = {
    "RECORD_MISSING_REFERENCE_ID": "Skipping record due to missing 'id': {record}",
    "RECORD_SKIPPED": "Skipped record '{reference_id_val}': {error}",
    "RECORD_SYNC_FAILURE": "Failed to sync DB record '{reference_id_val}': {error}",
    "REMOTE_API_FAILURE": "API Error fetching '{path}': {error}",
    "SYNC_COMPLETE": "Sync complete for '{entity}' with result {result} with '{errors_count}' erors.",
    "SYNC_START": "Start fetching '{entity}' data from HOPE core...",
}


class SkipRecordError(Exception):
    """Exception raised when a record should be skipped during synchronization."""


class ParamDateName(Enum):
    """Parameter names for date filtering in API requests."""

    UPDATED = "updated_at_after"
    MODIFIED = "modified_after"


class EndpointConfig(TypedDict):
    path: str
    params: NotRequired[dict[str, Any] | None]


class SyncConfig[T: Model](TypedDict):
    """Configuration for synchronizing an entity.

    Attributes:
        model: The Django model class to synchronize.
        delta_sync: If True, only new records will be processed; otherwise, existing records will be updated.
        endpoint: The API endpoint configuration with path and optional query parameters.
        reference_id: The field name used as the system reference ID for the model.
        prepare_defaults: Function to prepare default values for the model.
        should_process: Optional function to filter records before processing.
        post_process: Optional function to process the model instance after creation/update.

    """

    model: type[T]
    delta_sync: bool
    endpoint: EndpointConfig
    reference_id: str
    should_process: NotRequired[Callable[[dict[str, Any]], bool] | None]
    prepare_defaults: Callable[[dict[str, Any]], dict[str, Any] | None]
    post_process: NotRequired[Callable[[T, bool], None] | None]


class Stats(TypedDict):
    errors: list[str]
    add: int
    upd: int


@contextmanager
def log_to(
    out: TextIOBase,
    logger_name: str = "root",
    level: Literal[0, 10, 20, 30, 40, 50, 60] = logging.INFO,
    log_format: str = "%(levelname)s %(message)s",
) -> Iterator[None]:
    logger = logging.getLogger(logger_name)

    handlers_backup = tuple(logger.handlers)
    level_backup = logger.getEffectiveLevel()

    for handler in logger.handlers:
        logger.removeHandler(handler)

    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter(log_format))
    handler.setLevel(level)

    logger.addHandler(handler)
    logger.setLevel(level)

    try:
        yield None
    finally:
        logger.removeHandler(handler)
        for handler in handlers_backup:
            logger.addHandler(handler)
        logger.setLevel(level_backup)


def add_error(stats: Stats, error: str) -> None:
    stats["errors"].append(error)


def safe_get(client: HopeClient, endpoint: EndpointConfig, stats: Stats) -> Generator[dict[str, Any], None, None]:
    """Fetch data from the remote API safely, handling errors."""
    try:
        yield from client.get(**endpoint)
    except RemoteError as e:
        error = format_msg("REMOTE_API_FAILURE", path=endpoint.get("path"), error=str(e))
        add_error(stats, error)
        logging.error(error)


def format_msg(key: str, **kwargs: Any) -> str:
    if template := MESSAGES.get(key):
        try:
            return template.format(**kwargs).rstrip("\n")
        except KeyError as e:
            raise ValueError(f"Log format error for key '{key}': missing placeholder '{e}'. Provided args: {kwargs}")
    else:
        raise KeyError(f"Log key '{key}' not found in MESSAGES configuration.")


def validated_reference_id(record: dict[str, Any], out: TextIO) -> str | None:
    """Validate and retrieve the system reference ID from the record."""
    reference_id_val = record.get("id")
    if not reference_id_val:
        logging.warning(format_msg("RECORD_MISSING_REFERENCE_ID", record=record))
    return reference_id_val


def sync_entity[T: Model](config: SyncConfig[T], client: HopeClient | None = None, stats: Stats | None = None) -> Stats:
    """Synchronize an entity with the remote API.

    Args:
        config (SyncConfig): Configuration for the entity synchronization.
        out (TextIOBase): Output file to write to.
        client (HopeClient): HopeClient to use for synchronization.
        stats (dict[str, Any]): Synchronization results.

    Notes:
        - Fetches records from the API, processes them, and updates/creates model instances.
        - Logs synchronization start, errors, and completion.

    """
    should_process = config.get("should_process")
    prepare_defaults = config.get("prepare_defaults")
    post_process = config.get("post_process")
    reference_id = config.get("reference_id")

    model, model_name = config["model"], config["model"]._meta.model_name
    stats = stats or Stats(errors=[], add=0, upd=0)
    client = client or HopeClient()

    with cache.lock(f"sync-{model_name}"):
        logging.info(format_msg("SYNC_START", entity=model_name))
        for record in safe_get(client, config["endpoint"], stats):
            if not (reference_id_val := validated_reference_id(record, stats)):
                continue
            if should_process and not should_process(record):
                continue
            try:
                defaults = prepare_defaults(record) if prepare_defaults else None
                if defaults is None or not defaults:
                    continue
                instance, created = model.objects.update_or_create(
                    defaults=defaults, **{reference_id: reference_id_val}
                )
                if post_process:
                    post_process(instance, created)
                stats["add" if created else "upd"] += 1
            except SkipRecordError as e:
                logging.warning(format_msg("RECORD_SKIPPED", reference_id_val=reference_id_val, error=str(e)))
            except (DatabaseError, KeyError, AttributeError) as e:
                error = format_msg("RECORD_SYNC_FAILURE", reference_id_val=reference_id_val, error=str(e))
                add_error(stats, error)
                logging.error(error)
        SyncLog.objects.register_sync(model)
        logging.info(format_msg("SYNC_COMPLETE", entity=model_name, result=stats, errors_count=len(stats["errors"])))

        return stats


def _get_last_updated_date(model: type[Model]) -> str | None:
    """Get the last update date for the given model."""
    ct = ContentType.objects.get_for_model(model)
    last_sync = SyncLog.objects.filter(content_type=ct).order_by("-last_update_date").first()
    return last_sync.last_update_date.date().isoformat() if last_sync else None


def build_endpoint(path: str, model: type[Model], param_date_name: ParamDateName, delta_sync: bool) -> EndpointConfig:
    """Build the endpoint configuration for the API request."""
    params = {"format": "json"}
    if delta_sync and (last_date := _get_last_updated_date(model)):
        return EndpointConfig(path=path, params={param_date_name.value: last_date, **params})
    return EndpointConfig(path=path, params=params)
