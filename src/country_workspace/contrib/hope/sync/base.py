from typing import Any, Final, TypedDict, NotRequired, TypeVar
from collections.abc import Generator, Callable
from io import TextIOBase

from dataclasses import dataclass, field
from enum import Enum, auto

from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Model, Q
from django.contrib.contenttypes.models import ContentType

from country_workspace.exceptions import RemoteError

from ....models import SyncLog
from ..client import HopeClient


T = TypeVar("T", bound="BaseSync")


MESSAGES: Final[dict[str, str]] = {
    "DEACTIVATION_FAILURE": "Failed during deactivation for '{entity}' : {error}",
    "RECORDS_DEACTIVATED": "Deactivated '{count}' records '{entity}' (obsolete or marked inactive in source).",
    "RECORD_MISSING_REFERENCE_ID": "Skipping record due to missing 'id': {record}",
    "RECORD_SKIPPED": "Skipped record '{reference_id_val}': {error}",
    "RECORD_SYNC_FAILURE": "Failed to sync DB record '{reference_id_val}': {error}",
    "REMOTE_API_FAILURE": "API Error fetching '{path}': {error}",
    "SYNC_COMPLETE": "Sync complete for '{entity}' with result {result} with '{errors_count}' erors.",
    "SYNC_START": "Start fetching '{entity}' data from HOPE core...",
}


class SkipRecordError(Exception):
    """Exception raised when a record should be skipped during synchronization."""


class LogLevel(Enum):
    """Log levels for synchronization messages."""

    INFO = auto()
    ERROR = auto()


class EndpointConfig(TypedDict):
    path: str
    params: NotRequired[dict[str, Any] | None]


class SyncConfig(TypedDict):
    """Configuration for synchronizing an entity.

    Attributes:
        model: The Django model class to synchronize.
        endpoint: The API endpoint configuration with path and optional query parameters.
        reference_id: The field name used as the system reference ID for the model.
        prepare_defaults: Function to prepare default values for the model.
        should_process: Optional function to filter records before processing.
        post_process: Optional function to process the model instance after creation/update.
        should_deactivate: Optional function to determine if a record should be deactivated.

    """

    model: type[Model]
    endpoint: EndpointConfig
    reference_id: str
    should_process: NotRequired[Callable[[dict[str, Any]], bool] | None]
    prepare_defaults: Callable[[dict[str, Any]], dict[str, Any] | None]
    post_process: NotRequired[Callable[[Model, bool], None] | None]
    should_deactivate: NotRequired[Callable[["dict[str, Any]"], bool] | None]


class BaseSyncStep(Enum):
    """Base class for synchronization steps.

    Attributes:
        value: The enumeration value.
        sync_method: The method to execute for this step.

    """

    def __init__(self, value: Any, sync_method: Callable[["BaseSync"], None]) -> None:
        self._value_ = value
        self._sync_method = sync_method

    @property
    def func(self) -> Callable[["BaseSync"], None]:
        return self._sync_method


@dataclass
class BaseSync:
    """Base class for synchronization operations.

    Attributes:
        client: The client for fetching data from the remote API.
        stdout: Optional output stream for logging messages.
        total: Accumulated results of synchronization (e.g., counts of added/updated records).

    """

    client: HopeClient = field(default_factory=HopeClient)
    stdout: TextIOBase | None = None
    total: dict[str, Any] = field(default_factory=dict)

    def safe_get(self, endpoint: EndpointConfig) -> Generator[dict[str, Any], None, None]:
        """Fetch data from the remote API safely, handling errors."""
        try:
            yield from self.client.get(**endpoint)
        except RemoteError as e:
            self.emit_log("REMOTE_API_FAILURE", LogLevel.ERROR, path=endpoint.get("path"), error=str(e))

    def emit_log(self, key: str, level: LogLevel = LogLevel.INFO, **kwargs: Any) -> None:
        """Emit a log message with the specified key and level."""
        if template := MESSAGES.get(key):
            try:
                msg = template.format(**kwargs).rstrip("\n")
            except KeyError as e:
                raise ValueError(
                    f"Log format error for key '{key}': missing placeholder '{e}'. Provided args: {kwargs}"
                )
            if self.stdout:
                self.stdout.write(f"[{level.name}] {msg}\n")
                self.stdout.flush()
            if level == LogLevel.ERROR:
                self.total.setdefault("errors", []).append(msg)
        else:
            raise KeyError(f"Log key '{key}' not found in MESSAGES configuration.")

    def validated_reference_id(self, record: dict[str, Any]) -> str | None:
        """Validate and retrieve the system reference ID from the record."""
        reference_id_val = record.get("id")
        if not reference_id_val:
            self.emit_log("RECORD_MISSING_REFERENCE_ID", record=record)
        return reference_id_val

    def sync_entity(self, config: SyncConfig) -> None:
        """Synchronize an entity with the remote API.

        Args:
            config (SyncConfig): Configuration for the entity synchronization.

        Notes:
            - Fetches records from the API, processes them, and updates/creates model instances.
            - Logs synchronization start, errors, and completion.
            - Deactivates records based on the should_deactivate function, if specified.

        """
        model, model_name = config["model"], config["model"]._meta.model_name
        self.total.setdefault(model_name, {"add": 0, "upd": 0})
        should_process, prepare_defaults, post_process, should_deactivate, reference_id = (
            config.get(k, v)
            for k, v in (
                ("should_process", None),
                ("prepare_defaults", lambda _: {}),
                ("post_process", None),
                ("should_deactivate", None),
                ("reference_id", None),
            )
        )

        with cache.lock(f"sync-{model_name.lower()}"):
            self.emit_log("SYNC_START", entity=model_name)
            all_processed, inactive = set(), set()
            for record in self.safe_get(config["endpoint"]):
                if not (reference_id_val := self.validated_reference_id(record)):
                    continue
                all_processed.add(reference_id_val)
                if should_deactivate and should_deactivate(record):
                    inactive.add(reference_id_val)
                    continue
                if should_process and not should_process(record):
                    continue
                try:
                    defaults = prepare_defaults(record)
                    if defaults is None or not defaults:
                        continue
                    instance, created = model.objects.update_or_create(
                        defaults=defaults, **{reference_id: reference_id_val}
                    )
                    if post_process:
                        post_process(instance, created)
                    self.total[model_name]["add" if created else "upd"] += 1
                except SkipRecordError as e:
                    self.emit_log("RECORD_SKIPPED", reference_id_val=reference_id_val, error=str(e))
                except (DatabaseError, KeyError, AttributeError) as e:
                    self.emit_log(
                        "RECORD_SYNC_FAILURE", LogLevel.ERROR, reference_id_val=reference_id_val, error=str(e)
                    )
            if should_deactivate:
                self._deactivate_records(model, model_name, all_processed, inactive)
            SyncLog.objects.register_sync(model)
            self.emit_log(
                "SYNC_COMPLETE",
                entity=model_name,
                result=self.total[model_name],
                errors_count=len(self.total.get("errors", [])),
            )

    def _deactivate_records(self, model: type[Model], model_name: str, processed: set[str], inactive: set[str]) -> None:
        """Deactivate existed records in the database that are inactive or not present in the source."""
        self.total.setdefault(model_name, {})
        try:
            deactivated_count = model.objects.filter(
                Q(active=True) & (~Q(hope_id__in=processed) | Q(hope_id__in=inactive))
            ).update(active=False)
            if deactivated_count:
                self.total[model_name]["deactivated"] = deactivated_count
                self.emit_log("RECORDS_DEACTIVATED", count=deactivated_count, entity=model_name)
        except DatabaseError as e:
            self.emit_log("DEACTIVATION_FAILURE", LogLevel.ERROR, entity=model_name, error=str(e))

    def get_updated_at_after(self, model: type[Model]) -> str | None:
        """Get the last update date for the given model."""
        ct = ContentType.objects.get_for_model(model)
        last_sync = SyncLog.objects.filter(content_type=ct).order_by("-last_update_date").first()
        return last_sync.last_update_date.date().isoformat() if last_sync else None


def sync_context(
    context_class: type[T],
    step: BaseSyncStep | None,
    stdout: TextIOBase | None = None,
    **context_kwargs: Any,
) -> dict[str, Any]:
    """Run synchronization steps for a given context.

    Args:
        context_class (type[T]): The synchronization context class (inheriting from BaseSync).
        step (BaseSyncStep | None): Specific step to execute. If None, all steps are run.
        stdout (TextIOBase | None): Optional output stream for logging.
        **context_kwargs (Any): Additional keyword arguments to pass to the context class.

    Returns:
        dict[str, Any]: Synchronization results, including counts and errors.

    Notes:
        Executes the specified step or all steps defined in the context's SyncStep.
        Stops on errors.

    """
    sync = context_class(stdout=stdout, **context_kwargs)
    steps = (step,) if step else tuple(sync.__class__.SyncStep)
    for current_step in steps:
        current_step.func(sync)()
        if sync.total.get("errors"):
            return sync.total
    return sync.total
