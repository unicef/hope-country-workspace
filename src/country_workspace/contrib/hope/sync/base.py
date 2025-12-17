import logging
from collections.abc import Generator, Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from io import TextIOBase
from typing import Any, Final, TypedDict, NotRequired, Literal

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Model

from country_workspace.exceptions import RemoteError
from country_workspace.models import SyncLog
from ..client import HopeClient
from ..exceptions import HopeSyncError, SkipRecordError

logging.basicConfig()

logger = logging.getLogger(__name__)


MESSAGES: Final[dict[str, str]] = {
    "RECORD_MISSING_REFERENCE_ID": "Skipping record due to missing 'id': {record}",
    "RECORD_SKIPPED": "Skipped record '{reference_id_val}': {error}",
    "RECORD_SYNC_FAILURE": "Failed to sync DB record '{reference_id_val}': {error}",
    "REMOTE_API_FAILURE": "API Error fetching '{path}': {error}",
    "SYNC_COMPLETE": "Sync complete for '{entity}' with result {result} with '{errors_count}' errors.",
    "SYNC_START": "Start fetching '{entity}' data from HOPE core...",
}


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
        delta_sync: If True, the API request is constrained by a date param (see build_endpoint); otherwise full fetch.
        endpoint: The API endpoint configuration with path and optional query parameters.
        reference_id: The field name used as the system reference ID for the model.
        prepare_defaults: Function to map an API record into model defaults (required).
        should_process: Optional record-level filter predicate (truthy -> process).
        post_process: Optional hook after create/update; may raise to fail the sync.

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
    """Temporarily redirect logs of `logger_name` to a stream."""
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
    """Yield records from the remote API, converting RemoteError -> HopeSyncError."""
    try:
        yield from client.get(**endpoint)
    except RemoteError as e:
        error = format_msg("REMOTE_API_FAILURE", path=endpoint.get("path"), error=str(e))
        add_error(stats, error)
        logger.error(error)
        raise HopeSyncError(error) from e


def format_msg(key: str, **kwargs: Any) -> str:
    if template := MESSAGES.get(key):
        try:
            return template.format(**kwargs).rstrip("\n")
        except KeyError as e:
            raise ValueError(f"Log format error for key '{key}': missing placeholder '{e}'. Provided args: {kwargs}")
    else:
        raise KeyError(f"Log key '{key}' not found in MESSAGES configuration.")


def validated_reference_id(record: dict[str, Any]) -> str | None:
    """Return record['id'] if present; warn and return None otherwise."""
    reference_id_val = record.get("id")
    if not reference_id_val:
        logger.warning(format_msg("RECORD_MISSING_REFERENCE_ID", record=record))
    return reference_id_val


def sync_entity[T: Model](config: SyncConfig[T], client: HopeClient | None = None, stats: Stats | None = None) -> Stats:
    """Synchronize a single model using the provided `SyncConfig`.

    Args:
        config: Sync configuration (model, endpoint, mappers/hooks).
        client: Optional `HopeClient`, created by default.
        stats: Optional running stats; a new one is created if not provided.

    Returns:
        Stats: counts of added/updated records; empty `errors` on success.

    Raises:
        HopeSyncError: if remote API fails or any record-level errors were collected.

    """
    should_process = config.get("should_process")
    prepare_defaults = config.get("prepare_defaults")
    post_process = config.get("post_process")
    reference_id = config.get("reference_id")

    model, model_name = config["model"], config["model"]._meta.model_name
    stats = stats or Stats(errors=[], add=0, upd=0)
    client = client or HopeClient()

    with cache.lock(f"sync-{model_name}"):
        logger.info(format_msg("SYNC_START", entity=model_name))
        for record in safe_get(client, config["endpoint"], stats):
            if not (reference_id_val := validated_reference_id(record)):
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
                logger.warning(format_msg("RECORD_SKIPPED", reference_id_val=reference_id_val, error=str(e)))
            except (DatabaseError, KeyError, AttributeError) as e:
                error = format_msg("RECORD_SYNC_FAILURE", reference_id_val=reference_id_val, error=str(e))
                add_error(stats, error)
                logger.error(error)
        if stats["errors"]:
            raise HopeSyncError(stats["errors"])
        SyncLog.objects.register_sync(model)
        logger.info(format_msg("SYNC_COMPLETE", entity=model_name, result=stats, errors_count=0))
        return stats


def _get_last_updated_date(model: type[Model]) -> str | None:
    ct = ContentType.objects.get_for_model(model)
    last_sync = SyncLog.objects.filter(content_type=ct).order_by("-last_update_date").first()
    return last_sync.last_update_date.date().isoformat() if last_sync else None


def build_endpoint(path: str, model: type[Model], param_date_name: ParamDateName, delta_sync: bool) -> EndpointConfig:
    params = {"format": "json"}
    if delta_sync and (last_date := _get_last_updated_date(model)):
        return EndpointConfig(path=path, params={param_date_name.value: last_date, **params})
    return EndpointConfig(path=path, params=params)
